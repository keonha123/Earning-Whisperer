package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.infrastructure.websocket.TradeCommandMessage;
import com.earningwhisperer.presentation.trade.TradeCallbackRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("TradeService 단위 테스트")
class TradeServiceTest {

    @Mock private TradeRepository tradeRepository;
    @Mock private User mockUser;

    @InjectMocks
    private TradeService tradeService;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(tradeService, "pendingTtlSeconds", 30L);
    }

    @Test
    @DisplayName("AUTO_PILOT + BUY이면 PENDING Trade가 저장되고 PendingTradeResult가 반환된다")
    void AUTO_PILOT_BUY이면_PENDING_Trade가_생성된다() {
        // Arrange
        given(mockUser.getId()).willReturn(1L);
        Trade savedTrade = mock(Trade.class);
        given(savedTrade.getId()).willReturn(42L);
        given(tradeRepository.save(any())).willReturn(savedTrade);

        // Act
        PendingTradeResult result = tradeService.createPendingTrade(
                mockUser, 100L, "NVDA", TradeAction.BUY, TradingMode.AUTO_PILOT, 0.1, 0.8);

        // Assert
        assertThat(result).isNotNull();
        assertThat(result.tradeId()).isEqualTo(42L);
        verify(tradeRepository).save(any());
    }

    @Test
    @DisplayName("SEMI_AUTO + BUY이면 PENDING Trade가 생성된다")
    void SEMI_AUTO_BUY이면_PENDING_Trade가_생성된다() {
        // Arrange
        given(mockUser.getId()).willReturn(1L);
        Trade savedTrade = mock(Trade.class);
        given(savedTrade.getId()).willReturn(43L);
        given(tradeRepository.save(any())).willReturn(savedTrade);

        // Act
        PendingTradeResult result = tradeService.createPendingTrade(
                mockUser, 100L, "NVDA", TradeAction.BUY, TradingMode.SEMI_AUTO, 0.1, 0.8);

        // Assert
        assertThat(result).isNotNull();
        assertThat(result.tradeId()).isEqualTo(43L);
        verify(tradeRepository).save(any());
    }

    @Test
    @DisplayName("HOLD이면 Trade가 생성되지 않고 null이 반환된다")
    void HOLD이면_Trade가_생성되지_않는다() {
        // Act
        PendingTradeResult result = tradeService.createPendingTrade(
                mockUser, 100L, "NVDA", TradeAction.HOLD, TradingMode.AUTO_PILOT, 0.1, 0.8);

        // Assert
        assertThat(result).isNull();
        verify(tradeRepository, never()).save(any());
    }

    @Test
    @DisplayName("MANUAL 모드이면 Trade가 생성되지 않고 null이 반환된다")
    void MANUAL_모드이면_Trade가_생성되지_않는다() {
        // Act
        PendingTradeResult result = tradeService.createPendingTrade(
                mockUser, 100L, "NVDA", TradeAction.BUY, TradingMode.MANUAL, 0.1, 0.8);

        // Assert
        assertThat(result).isNull();
        verify(tradeRepository, never()).save(any());
    }

    @Test
    @DisplayName("callback 시 Trade 소유자가 다르면 SecurityException이 발생한다")
    void callback_소유권_불일치시_예외발생() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);

        // Act & Assert — callerId=2L은 소유자(1L)와 다름
        assertThatThrownBy(() -> tradeService.processCallback(99L, 2L, request))
                .isInstanceOf(SecurityException.class);
    }

    @Test
    @DisplayName("callback EXECUTED 시 Trade 상태가 EXECUTED로 변경된다")
    void callback_EXECUTED_정상처리() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("EXECUTED");
        given(request.getExecutedQty()).willReturn(10);
        given(request.getExecutedPrice()).willReturn(125.50);
        given(request.getBrokerOrderId()).willReturn("BROKER-001");

        // Act
        tradeService.processCallback(99L, 1L, request);

        // Assert
        verify(trade).executed(10, 125.50, "BROKER-001");
        verify(tradeRepository).save(trade);
    }

    @Test
    @DisplayName("callback FAILED 시 Trade 상태가 FAILED로 변경된다")
    void callback_FAILED_정상처리() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("FAILED");

        // Act
        tradeService.processCallback(99L, 1L, request);

        // Assert
        verify(trade).failed();
        verify(tradeRepository).save(trade);
    }

    @Test
    @DisplayName("processCallback 은 비관적 락 메서드(findByIdForUpdate)로 Trade 를 조회한다 — 회귀 보호")
    void processCallback_비관적_락_메서드_사용_회귀_보호() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(tradeRepository.findByIdForUpdate(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("FAILED");

        // Act
        tradeService.processCallback(99L, 1L, request);

        // Assert — 동시 콜백 lost update 차단을 위해 반드시 락 메서드를 사용해야 한다.
        verify(tradeRepository).findByIdForUpdate(99L);
        verify(tradeRepository, never()).findById(99L);
    }

    @Test
    @DisplayName("getPendingCommandsForUser - 활성 broker 의 미만료 PENDING 을 TradeCommandMessage 로 변환")
    void getPendingCommandsForUser_미만료_PENDING_변환() {
        // Arrange
        Trade trade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(trade.getUser()).willReturn(owner);
        given(trade.getId()).willReturn(7L);
        given(trade.getSide()).willReturn(TradeAction.BUY);
        given(trade.getBrokerAccountId()).willReturn(100L);
        given(trade.getOrderRatio()).willReturn(0.1);
        given(trade.getAiScore()).willReturn(0.85);
        given(trade.getTicker()).willReturn("NVDA");

        given(tradeRepository.findByBrokerAccountIdAndStatusAndCreatedAtAfter(
                eq(100L), eq(TradeStatus.PENDING), any(LocalDateTime.class)))
                .willReturn(List.of(trade));

        // Act
        List<TradeCommandMessage> result = tradeService.getPendingCommandsForUser(1L, 100L);

        // Assert
        assertThat(result).hasSize(1);
        TradeCommandMessage cmd = result.get(0);
        assertThat(cmd.getTradeId()).isEqualTo(7L);
        assertThat(cmd.getBrokerAccountId()).isEqualTo(100L);
        assertThat(cmd.getAction()).isEqualTo("BUY");
        assertThat(cmd.getOrderRatio()).isEqualTo(0.1);
        assertThat(cmd.getTicker()).isEqualTo("NVDA");
        assertThat(cmd.getAiScore()).isEqualTo(0.85);
    }

    @Test
    @DisplayName("getPendingCommandsForUser - orderRatio/aiScore 가 null 인 레거시 행은 제외")
    void getPendingCommandsForUser_레거시_행_제외() {
        // Arrange — orderRatio 만 null 이어도 filter 에서 제외 (aiScore 검사 도달 X)
        Trade legacyTrade = mock(Trade.class);
        User owner = mock(User.class);
        given(owner.getId()).willReturn(1L);
        given(legacyTrade.getUser()).willReturn(owner);
        given(legacyTrade.getOrderRatio()).willReturn(null);

        given(tradeRepository.findByBrokerAccountIdAndStatusAndCreatedAtAfter(
                eq(100L), eq(TradeStatus.PENDING), any(LocalDateTime.class)))
                .willReturn(List.of(legacyTrade));

        // Act
        List<TradeCommandMessage> result = tradeService.getPendingCommandsForUser(1L, 100L);

        // Assert
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("expireStalePending - Repository 의 단일 UPDATE 결과를 그대로 반환")
    void expireStalePending_UPDATE_결과_반환() {
        given(tradeRepository.expirePendingBefore(any(LocalDateTime.class))).willReturn(3);

        int count = tradeService.expireStalePending();

        assertThat(count).isEqualTo(3);
        verify(tradeRepository).expirePendingBefore(any(LocalDateTime.class));
    }

    @Test
    @DisplayName("expireStalePending - 대상이 없으면 0 반환")
    void expireStalePending_대상_없음() {
        given(tradeRepository.expirePendingBefore(any(LocalDateTime.class))).willReturn(0);

        int count = tradeService.expireStalePending();

        assertThat(count).isZero();
    }
}
