package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.ProcessedSignal;
import com.earningwhisperer.domain.signal.SignalService;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.infrastructure.websocket.LiveSignalPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("TradingSignalSubscriber 단위 테스트")
class TradingSignalSubscriberTest {

    @Mock
    private SignalService signalService;

    @Mock
    private LiveSignalPublisher liveSignalPublisher;

    @Spy
    private ObjectMapper objectMapper;

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
    @DisplayName("정상 메시지 수신 시 SignalService.processSignal()이 호출된다")
    void 정상_메시지_수신시_SignalService가_호출된다() {
        // Arrange
        when(signalService.processSignal(any())).thenReturn(new ProcessedSignal(0.8, TradeAction.BUY));

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert
        verify(signalService).processSignal(any());
    }

    @Test
    @DisplayName("정상 메시지 수신 시 LiveSignalPublisher.publish()가 1회 호출된다")
    void 정상_메시지_수신시_WebSocket_브로드캐스트가_호출된다() {
        // Arrange
        when(signalService.processSignal(any())).thenReturn(new ProcessedSignal(0.8, TradeAction.HOLD));

        // Act
        subscriber.handleMessage(VALID_MESSAGE);

        // Assert
        verify(liveSignalPublisher).publish(any());
    }

    @Test
    @DisplayName("JSON 파싱 실패 시 SignalService와 LiveSignalPublisher 모두 호출되지 않는다")
    void JSON_파싱_실패시_서비스와_Publisher는_호출되지_않는다() {
        // Act
        subscriber.handleMessage("{ invalid json }");

        // Assert
        verify(signalService, never()).processSignal(any());
        verify(liveSignalPublisher, never()).publish(any());
    }

    @Test
    @DisplayName("빈 문자열 수신 시 SignalService와 LiveSignalPublisher 모두 호출되지 않는다")
    void 빈_문자열_수신시_서비스와_Publisher는_호출되지_않는다() {
        // Act
        subscriber.handleMessage("");

        // Assert
        verify(signalService, never()).processSignal(any());
        verify(liveSignalPublisher, never()).publish(any());
    }
}
