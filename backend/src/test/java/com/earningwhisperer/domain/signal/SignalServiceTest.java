package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.BrokerAccount;
import com.earningwhisperer.domain.portfolio.BrokerAccountService;
import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.PositionService;
import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.infrastructure.redis.TradingSignalMessage;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("SignalService 단위 테스트")
class SignalServiceTest {

    @Mock private PortfolioSettingsService portfolioSettingsService;
    @Mock private PositionService positionService;
    @Mock private BrokerAccountService brokerAccountService;
    @Mock private SignalHistoryRepository signalHistoryRepository;

    @InjectMocks
    private SignalService signalService;

    private TradingSignalMessage signal;
    private static final long ACTIVE_BROKER_ID = 100L;

    @BeforeEach
    void setUp() {
        signal = buildSignal("NVDA", 0.75);
    }

    /** 활성 BrokerAccount + cashBalance 갖춘 정상 사용자 stub. */
    private PortfolioSettings stubSingleUser(TradingMode mode, double threshold) {
        User user = org.mockito.Mockito.mock(User.class);
        given(user.getId()).willReturn(1L);
        PortfolioSettings settings = org.mockito.Mockito.mock(PortfolioSettings.class);
        given(settings.getUser()).willReturn(user);
        given(settings.getCooldownMinutes()).willReturn(5);
        given(settings.getAiScoreThreshold()).willReturn(threshold);
        given(settings.getTradingMode()).willReturn(mode);
        given(settings.getBuyAmountRatio()).willReturn(0.1);
        given(settings.getMaxPositionRatio()).willReturn(1.0);
        given(portfolioSettingsService.getAllSettings()).willReturn(List.of(settings));

        BrokerAccount active = org.mockito.Mockito.mock(BrokerAccount.class);
        given(active.getId()).willReturn(ACTIVE_BROKER_ID);
        given(active.getCashBalance()).willReturn(10_000.0);
        given(brokerAccountService.getActive(1L)).willReturn(Optional.of(active));
        return settings;
    }

    @Test
    @DisplayName("임계치 초과 aiScore이면 BUY action이 반환된다")
    void 임계치_초과이면_BUY_반환() {
        stubSingleUser(TradingMode.AUTO_PILOT, 0.6);
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.BUY);
        assertThat(results.get(0).aiScore()).isEqualTo(0.75);
        assertThat(results.get(0).brokerAccountId()).isEqualTo(ACTIVE_BROKER_ID);
    }

    @Test
    @DisplayName("임계치 미달 aiScore이면 HOLD action이 반환된다")
    void 임계치_미달이면_HOLD_반환() {
        stubSingleUser(TradingMode.AUTO_PILOT, 0.9);
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("MANUAL 모드이면 aiScore에 관계없이 HOLD가 반환된다")
    void MANUAL_모드이면_HOLD_반환() {
        stubSingleUser(TradingMode.MANUAL, 0.6);
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("쿨다운 중이면 HOLD가 반환되고 SignalHistory는 저장된다")
    void 쿨다운_중이면_HOLD_반환() {
        stubSingleUser(TradingMode.AUTO_PILOT, 0.6);
        SignalHistory recentSignal = mockRecentSignal(LocalDateTime.now().minusMinutes(1));
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.of(recentSignal));

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("processSignalForAllUsers 호출 시 SignalHistory가 batch 저장된다")
    void processSignalForAllUsers_호출시_SignalHistory가_저장된다() {
        stubSingleUser(TradingMode.AUTO_PILOT, 0.6);
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        signalService.processSignalForAllUsers(signal);

        verify(signalHistoryRepository).saveAll(anyList());
    }

    @Test
    @DisplayName("쿨다운 만료 후 신호는 정상 처리된다")
    void 쿨다운_만료_후_신호는_정상처리된다() {
        stubSingleUser(TradingMode.AUTO_PILOT, 0.6);
        SignalHistory oldSignal = mockRecentSignal(LocalDateTime.now().minusMinutes(10));
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.of(oldSignal));

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.BUY);
    }

    @Test
    @DisplayName("활성 BrokerAccount 미설정 사용자는 fail-safe HOLD + brokerAccountId=null")
    void 활성_BrokerAccount_없으면_HOLD() {
        User user = org.mockito.Mockito.mock(User.class);
        given(user.getId()).willReturn(1L);
        PortfolioSettings settings = org.mockito.Mockito.mock(PortfolioSettings.class);
        given(settings.getUser()).willReturn(user);
        given(settings.getCooldownMinutes()).willReturn(5);
        given(settings.getBuyAmountRatio()).willReturn(0.1);
        given(settings.getMaxPositionRatio()).willReturn(1.0);
        given(portfolioSettingsService.getAllSettings()).willReturn(List.of(settings));
        given(brokerAccountService.getActive(1L)).willReturn(Optional.empty()); // 핵심
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.HOLD);
        assertThat(results.get(0).brokerAccountId()).isNull();
    }

    @Test
    @DisplayName("cashBalance 가 null (KIS sync 미완료) 이면 fail-safe HOLD")
    void cashBalance_null이면_fail_safe_HOLD() {
        User user = org.mockito.Mockito.mock(User.class);
        given(user.getId()).willReturn(1L);
        PortfolioSettings settings = org.mockito.Mockito.mock(PortfolioSettings.class);
        given(settings.getUser()).willReturn(user);
        given(settings.getCooldownMinutes()).willReturn(5);
        given(settings.getBuyAmountRatio()).willReturn(0.1);
        given(settings.getMaxPositionRatio()).willReturn(1.0);
        given(portfolioSettingsService.getAllSettings()).willReturn(List.of(settings));

        BrokerAccount active = org.mockito.Mockito.mock(BrokerAccount.class);
        given(active.getId()).willReturn(ACTIVE_BROKER_ID);
        given(active.getCashBalance()).willReturn(null);
        given(brokerAccountService.getActive(1L)).willReturn(Optional.of(active));

        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("BUY 시그널이지만 ticker 보유 비중이 maxPositionRatio 한도에 도달하면 HOLD")
    void maxPositionRatio_도달시_BUY가_HOLD로_변경된다() {
        User user = org.mockito.Mockito.mock(User.class);
        given(user.getId()).willReturn(1L);
        PortfolioSettings settings = org.mockito.Mockito.mock(PortfolioSettings.class);
        given(settings.getUser()).willReturn(user);
        given(settings.getCooldownMinutes()).willReturn(5);
        given(settings.getAiScoreThreshold()).willReturn(0.6);
        given(settings.getTradingMode()).willReturn(TradingMode.AUTO_PILOT);
        given(settings.getBuyAmountRatio()).willReturn(0.1);
        given(settings.getMaxPositionRatio()).willReturn(0.30);
        given(portfolioSettingsService.getAllSettings()).willReturn(List.of(settings));

        BrokerAccount active = org.mockito.Mockito.mock(BrokerAccount.class);
        given(active.getId()).willReturn(ACTIVE_BROKER_ID);
        given(active.getCashBalance()).willReturn(10_000.0);
        given(brokerAccountService.getActive(1L)).willReturn(Optional.of(active));

        given(positionService.computeBookRatio(eq(ACTIVE_BROKER_ID), eq("NVDA"), eq(10_000.0)))
                .willReturn(0.25);
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(1);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("사용자가 없으면 빈 리스트가 반환된다")
    void 사용자가_없으면_빈_리스트가_반환된다() {
        given(portfolioSettingsService.getAllSettings()).willReturn(List.of());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).isEmpty();
    }

    // --- 헬퍼 ---

    private TradingSignalMessage buildSignal(String ticker, double aiScore) {
        try {
            String json = """
                    {"ticker":"%s","ai_score":%s,"rationale":"test","text_chunk":"chunk","timestamp":1710000000}
                    """.formatted(ticker, aiScore);
            return new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, TradingSignalMessage.class);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private SignalHistory mockRecentSignal(LocalDateTime createdAt) {
        SignalHistory mock = org.mockito.Mockito.mock(SignalHistory.class);
        given(mock.getCreatedAt()).willReturn(createdAt);
        return mock;
    }
}
