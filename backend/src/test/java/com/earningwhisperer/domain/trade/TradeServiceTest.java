package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.infrastructure.broker.BrokerApiClient;
import com.earningwhisperer.infrastructure.broker.BrokerApiException;
import com.earningwhisperer.infrastructure.broker.BrokerOrderRequest;
import com.earningwhisperer.infrastructure.broker.BrokerOrderResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("TradeService 단위 테스트")
class TradeServiceTest {

    @Mock private TradeRepository tradeRepository;
    @Mock private UserRepository userRepository;
    @Mock private PortfolioSettingsService portfolioSettingsService;
    @Mock private BrokerApiClient brokerApiClient;
    @Mock private PortfolioSettings mockSettings;
    @Mock private User mockUser;

    @InjectMocks
    private TradeService tradeService;

    @Test
    @DisplayName("AUTO_PILOT + BUY이면 BrokerApiClient가 호출되고 executedQty가 반환된다")
    void AUTO_PILOT_BUY이면_주문이_실행된다() {
        // Arrange
        given(portfolioSettingsService.getSettings(any())).willReturn(mockSettings);
        given(mockSettings.getTradingMode()).willReturn(TradingMode.AUTO_PILOT);
        given(userRepository.findById(any())).willReturn(Optional.of(mockUser));
        given(tradeRepository.save(any())).willAnswer(inv -> inv.getArgument(0));
        given(brokerApiClient.placeOrder(any(BrokerOrderRequest.class)))
                .willReturn(new BrokerOrderResponse("ORD-001", 1));

        // Act
        int result = tradeService.execute("NVDA", TradeAction.BUY);

        // Assert
        assertThat(result).isEqualTo(1);
        verify(brokerApiClient).placeOrder(any());
        verify(tradeRepository, times(2)).save(any()); // PENDING + EXECUTED
    }

    @Test
    @DisplayName("HOLD이면 BrokerApiClient가 호출되지 않고 0이 반환된다")
    void HOLD이면_주문이_실행되지_않는다() {
        // Act
        int result = tradeService.execute("NVDA", TradeAction.HOLD);

        // Assert
        assertThat(result).isEqualTo(0);
        verify(brokerApiClient, never()).placeOrder(any());
        verify(tradeRepository, never()).save(any());
    }

    @Test
    @DisplayName("MANUAL 모드이면 BrokerApiClient가 호출되지 않고 0이 반환된다")
    void MANUAL_모드이면_주문이_실행되지_않는다() {
        // Arrange
        given(portfolioSettingsService.getSettings(any())).willReturn(mockSettings);
        given(mockSettings.getTradingMode()).willReturn(TradingMode.MANUAL);

        // Act
        int result = tradeService.execute("NVDA", TradeAction.BUY);

        // Assert
        assertThat(result).isEqualTo(0);
        verify(brokerApiClient, never()).placeOrder(any());
    }

    @Test
    @DisplayName("BrokerApiClient 예외 발생 시 trade.failed()가 저장되고 0이 반환된다")
    void 브로커_예외시_Trade가_FAILED로_저장된다() {
        // Arrange
        given(portfolioSettingsService.getSettings(any())).willReturn(mockSettings);
        given(mockSettings.getTradingMode()).willReturn(TradingMode.AUTO_PILOT);
        given(userRepository.findById(any())).willReturn(Optional.of(mockUser));
        given(tradeRepository.save(any())).willAnswer(inv -> inv.getArgument(0));
        given(brokerApiClient.placeOrder(any()))
                .willThrow(new BrokerApiException("KIS API 오류"));

        // Act
        int result = tradeService.execute("NVDA", TradeAction.BUY);

        // Assert
        assertThat(result).isEqualTo(0);
        verify(tradeRepository, times(2)).save(any()); // PENDING + FAILED
    }
}
