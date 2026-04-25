package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
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
    @Mock private SignalHistoryRepository signalHistoryRepository;

    @InjectMocks
    private SignalService signalService;

    private TradingSignalMessage signal;

    @BeforeEach
    void setUp() {
        signal = buildSignal("NVDA", 0.75);
    }

    private PortfolioSettings stubSingleUser(TradingMode mode, double threshold) {
        User user = org.mockito.Mockito.mock(User.class);
        given(user.getId()).willReturn(1L);
        PortfolioSettings settings = org.mockito.Mockito.mock(PortfolioSettings.class);
        given(settings.getUser()).willReturn(user);
        given(settings.getCooldownMinutes()).willReturn(5);
        given(settings.getAiScoreThreshold()).willReturn(threshold);
        given(settings.getTradingMode()).willReturn(mode);
        given(portfolioSettingsService.getAllSettings()).willReturn(List.of(settings));
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
    @DisplayName("다중 사용자는 각자의 설정으로 다른 action이 반환된다")
    void 다중_사용자_각각_다른_설정으로_다른_action이_반환된다() {
        User userA = org.mockito.Mockito.mock(User.class);
        User userB = org.mockito.Mockito.mock(User.class);
        given(userA.getId()).willReturn(1L);
        given(userB.getId()).willReturn(2L);

        PortfolioSettings settingsA = org.mockito.Mockito.mock(PortfolioSettings.class);
        PortfolioSettings settingsB = org.mockito.Mockito.mock(PortfolioSettings.class);
        given(settingsA.getUser()).willReturn(userA);
        given(settingsA.getCooldownMinutes()).willReturn(5);
        given(settingsA.getAiScoreThreshold()).willReturn(0.6);
        given(settingsA.getTradingMode()).willReturn(TradingMode.AUTO_PILOT);

        given(settingsB.getUser()).willReturn(userB);
        given(settingsB.getCooldownMinutes()).willReturn(5);
        given(settingsB.getAiScoreThreshold()).willReturn(0.9);
        given(settingsB.getTradingMode()).willReturn(TradingMode.MANUAL);

        given(portfolioSettingsService.getAllSettings()).willReturn(List.of(settingsA, settingsB));
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());

        List<UserProcessedSignal> results = signalService.processSignalForAllUsers(signal);

        assertThat(results).hasSize(2);
        assertThat(results.get(0).action()).isEqualTo(TradeAction.BUY);   // threshold=0.6, AUTO_PILOT
        assertThat(results.get(1).action()).isEqualTo(TradeAction.HOLD);  // MANUAL → 항상 HOLD
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
