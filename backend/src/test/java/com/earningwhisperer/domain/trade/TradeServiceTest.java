package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.presentation.trade.TradeCallbackRequest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("TradeService 단위 테스트")
class TradeServiceTest {

    @Mock private TradeRepository tradeRepository;
    @Mock private User mockUser;

    @InjectMocks
    private TradeService tradeService;

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
                mockUser, "NVDA", TradeAction.BUY, TradingMode.AUTO_PILOT);

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
                mockUser, "NVDA", TradeAction.BUY, TradingMode.SEMI_AUTO);

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
                mockUser, "NVDA", TradeAction.HOLD, TradingMode.AUTO_PILOT);

        // Assert
        assertThat(result).isNull();
        verify(tradeRepository, never()).save(any());
    }

    @Test
    @DisplayName("MANUAL 모드이면 Trade가 생성되지 않고 null이 반환된다")
    void MANUAL_모드이면_Trade가_생성되지_않는다() {
        // Act
        PendingTradeResult result = tradeService.createPendingTrade(
                mockUser, "NVDA", TradeAction.BUY, TradingMode.MANUAL);

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
        given(tradeRepository.findById(99L)).willReturn(Optional.of(trade));

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
        given(tradeRepository.findById(99L)).willReturn(Optional.of(trade));

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
        given(tradeRepository.findById(99L)).willReturn(Optional.of(trade));

        TradeCallbackRequest request = mock(TradeCallbackRequest.class);
        given(request.getStatus()).willReturn("FAILED");

        // Act
        tradeService.processCallback(99L, 1L, request);

        // Assert
        verify(trade).failed();
        verify(tradeRepository).save(trade);
    }
}
