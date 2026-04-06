package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.SignalService;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.signal.UserProcessedSignal;
import com.earningwhisperer.domain.trade.PendingTradeResult;
import com.earningwhisperer.domain.trade.TradeService;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.infrastructure.websocket.LiveSignalPublisher;
import com.earningwhisperer.infrastructure.websocket.TradeCommandPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("TradingSignalSubscriber 단위 테스트")
class TradingSignalSubscriberTest {

    @Mock private SignalService signalService;
    @Mock private TradeService tradeService;
    @Mock private LiveSignalPublisher liveSignalPublisher;
    @Mock private TradeCommandPublisher tradeCommandPublisher;
    @Spy  private ObjectMapper objectMapper;

    @InjectMocks
    private TradingSignalSubscriber subscriber;

    private static final String VALID_MESSAGE = """
            {
              "ticker": "NVDA",
              "raw_score": 0.85,
              "rationale": "Strong earnings beat",
              "text_chunk": "Revenue exceeded expectations",
              "timestamp": 1710000000
            }
            """;

    @Test
    @DisplayName("정상 메시지 수신 시 SignalService → TradeService → Publisher 순서로 호출된다")
    void 정상_메시지_처리_순서_검증() {
        // Arrange
        User user1 = mock(User.class);
        List<UserProcessedSignal> results = List.of(
                new UserProcessedSignal(user1, TradeAction.BUY, 0.8, TradingMode.AUTO_PILOT));
        when(signalService.processSignalForAllUsers(any())).thenReturn(results);
        when(tradeService.createPendingTrade(eq(user1), anyString(), any(), any()))
                .thenReturn(new PendingTradeResult(1L, 1L));

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert — 호출 순서 검증
        InOrder inOrder = inOrder(signalService, tradeService, liveSignalPublisher);
        inOrder.verify(signalService).processSignalForAllUsers(any());
        inOrder.verify(tradeService).createPendingTrade(eq(user1), eq("NVDA"), eq(TradeAction.BUY), eq(TradingMode.AUTO_PILOT));
        inOrder.verify(liveSignalPublisher).publish(any());
        verify(tradeCommandPublisher).publish(eq(1L), any());
    }

    @Test
    @DisplayName("다중 사용자 팬아웃 — 각 사용자에게 Trade 생성 및 WebSocket 전송")
    void 다중_사용자_팬아웃_처리() {
        // Arrange
        User user1 = mock(User.class);
        User user2 = mock(User.class);

        List<UserProcessedSignal> results = List.of(
                new UserProcessedSignal(user1, TradeAction.BUY, 0.8, TradingMode.AUTO_PILOT),
                new UserProcessedSignal(user2, TradeAction.BUY, 0.8, TradingMode.SEMI_AUTO));
        when(signalService.processSignalForAllUsers(any())).thenReturn(results);
        when(tradeService.createPendingTrade(eq(user1), anyString(), any(), any()))
                .thenReturn(new PendingTradeResult(10L, 1L));
        when(tradeService.createPendingTrade(eq(user2), anyString(), any(), any()))
                .thenReturn(new PendingTradeResult(11L, 2L));

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert
        verify(tradeCommandPublisher).publish(eq(1L), any());
        verify(tradeCommandPublisher).publish(eq(2L), any());
        verify(liveSignalPublisher).publish(any());
    }

    @Test
    @DisplayName("MANUAL 사용자에게는 TradeCommand가 전송되지 않는다")
    void MANUAL_사용자에게는_TradeCommand가_전송되지_않는다() {
        // Arrange
        User user1 = mock(User.class);
        List<UserProcessedSignal> results = List.of(
                new UserProcessedSignal(user1, TradeAction.HOLD, 0.8, TradingMode.MANUAL));
        when(signalService.processSignalForAllUsers(any())).thenReturn(results);
        when(tradeService.createPendingTrade(any(User.class), anyString(), any(), any()))
                .thenReturn(null);

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert
        verify(tradeCommandPublisher, never()).publish(any(), any());
        verify(liveSignalPublisher).publish(any());
    }

    @Test
    @DisplayName("JSON 파싱 실패 시 SignalService, TradeService, Publisher 모두 호출되지 않는다")
    void JSON_파싱_실패시_모든_서비스가_호출되지_않는다() {
        // Act
        subscriber.handleMessage("{ invalid json }");

        // Assert
        verify(signalService, never()).processSignalForAllUsers(any());
        verify(tradeService, never()).createPendingTrade(any(User.class), anyString(), any(), any());
        verify(liveSignalPublisher, never()).publish(any());
    }

    @Test
    @DisplayName("빈 문자열 수신 시 모든 서비스가 호출되지 않는다")
    void 빈_문자열_수신시_모든_서비스가_호출되지_않는다() {
        // Act
        subscriber.handleMessage("");

        // Assert
        verify(signalService, never()).processSignalForAllUsers(any());
        verify(tradeService, never()).createPendingTrade(any(User.class), anyString(), any(), any());
        verify(liveSignalPublisher, never()).publish(any());
    }

    @Test
    @DisplayName("특정 사용자 Trade 생성 실패 시 다른 사용자는 정상 처리된다")
    void 사용자별_Trade_실패_격리_검증() {
        // Arrange
        User user1 = mock(User.class);
        when(user1.getId()).thenReturn(1L);
        User user2 = mock(User.class);

        List<UserProcessedSignal> results = List.of(
                new UserProcessedSignal(user1, TradeAction.BUY, 0.8, TradingMode.AUTO_PILOT),
                new UserProcessedSignal(user2, TradeAction.BUY, 0.8, TradingMode.AUTO_PILOT));
        when(signalService.processSignalForAllUsers(any())).thenReturn(results);

        // user1 Trade 생성 시 예외 발생
        when(tradeService.createPendingTrade(eq(user1), anyString(), any(), any()))
                .thenThrow(new RuntimeException("DB 오류"));
        when(tradeService.createPendingTrade(eq(user2), anyString(), any(), any()))
                .thenReturn(new PendingTradeResult(11L, 2L));

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert — user2는 정상 처리, 브로드캐스트도 실행
        verify(tradeCommandPublisher).publish(eq(2L), any());
        verify(liveSignalPublisher).publish(any());
    }

    @Test
    @DisplayName("SELL 시그널 처리 시 Trade 생성 및 WebSocket 전송")
    void SELL_시그널_처리() {
        // Arrange
        User user1 = mock(User.class);
        List<UserProcessedSignal> results = List.of(
                new UserProcessedSignal(user1, TradeAction.SELL, -0.8, TradingMode.AUTO_PILOT));
        when(signalService.processSignalForAllUsers(any())).thenReturn(results);
        when(tradeService.createPendingTrade(eq(user1), anyString(), any(), any()))
                .thenReturn(new PendingTradeResult(20L, 1L));

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert
        verify(tradeService).createPendingTrade(eq(user1), eq("NVDA"), eq(TradeAction.SELL), eq(TradingMode.AUTO_PILOT));
        verify(tradeCommandPublisher).publish(eq(1L), any());
        verify(liveSignalPublisher).publish(any());
    }
}
