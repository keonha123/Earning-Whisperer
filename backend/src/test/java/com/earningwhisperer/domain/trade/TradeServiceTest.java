package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
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
    @Mock private UserRepository userRepository;
    @Mock private PortfolioSettingsService portfolioSettingsService;
    @Mock private PortfolioSettings mockSettings;
    @Mock private User mockUser;

    @InjectMocks
    private TradeService tradeService;

    @Test
    @DisplayName("AUTO_PILOT + BUY이면 PENDING Trade가 저장되고 PendingTradeResult가 반환된다")
    void AUTO_PILOT_BUY이면_PENDING_Trade가_생성된다() {
        // Arrange
        given(portfolioSettingsService.getSettings(any())).willReturn(mockSettings);
        given(mockSettings.getTradingMode()).willReturn(TradingMode.AUTO_PILOT);
        given(userRepository.findById(any())).willReturn(Optional.of(mockUser));
        Trade savedTrade = mock(Trade.class);
        given(savedTrade.getId()).willReturn(42L);
        given(tradeRepository.save(any())).willReturn(savedTrade);

        // Act
        PendingTradeResult result = tradeService.createPendingTrade("NVDA", TradeAction.BUY);

        // Assert
        assertThat(result).isNotNull();
        assertThat(result.tradeId()).isEqualTo(42L);
        verify(tradeRepository).save(any());
    }

    @Test
    @DisplayName("HOLD이면 Trade가 생성되지 않고 null이 반환된다")
    void HOLD이면_Trade가_생성되지_않는다() {
        // Act
        PendingTradeResult result = tradeService.createPendingTrade("NVDA", TradeAction.HOLD);

        // Assert
        assertThat(result).isNull();
        verify(tradeRepository, never()).save(any());
    }

    @Test
    @DisplayName("MANUAL 모드이면 Trade가 생성되지 않고 null이 반환된다")
    void MANUAL_모드이면_Trade가_생성되지_않는다() {
        // Arrange
        given(portfolioSettingsService.getSettings(any())).willReturn(mockSettings);
        given(mockSettings.getTradingMode()).willReturn(TradingMode.MANUAL);

        // Act
        PendingTradeResult result = tradeService.createPendingTrade("NVDA", TradeAction.BUY);

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
}
