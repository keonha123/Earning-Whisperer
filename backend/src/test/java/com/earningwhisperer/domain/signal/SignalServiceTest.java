package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.infrastructure.redis.TradingSignalMessage;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("SignalService 단위 테스트")
class SignalServiceTest {

    @Mock private EmaService emaService;
    @Mock private PortfolioSettingsService portfolioSettingsService;
    @Mock private SignalHistoryRepository signalHistoryRepository;
    @Mock private UserRepository userRepository;
    @Mock private PortfolioSettings mockSettings;
    @Mock private User mockUser;

    @InjectMocks
    private SignalService signalService;

    private TradingSignalMessage signal;

    @BeforeEach
    void setUp() {
        signal = buildSignal("NVDA", 0.85);
        given(portfolioSettingsService.getSettings(SignalService.SYSTEM_USER_ID))
                .willReturn(mockSettings);
        given(mockSettings.getCooldownMinutes()).willReturn(5);
        given(mockSettings.getEmaThreshold()).willReturn(0.6);
        given(mockSettings.getTradingMode()).willReturn(TradingMode.AUTO_PILOT);
        given(userRepository.findById(SignalService.SYSTEM_USER_ID)).willReturn(Optional.of(mockUser));
    }

    @Test
    @DisplayName("임계치 초과 emaScore이면 BUY action이 반환된다")
    void 임계치_초과이면_BUY_반환() {
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());
        given(emaService.process("NVDA", 0.85)).willReturn(0.75);

        ProcessedSignal result = signalService.processSignal(signal);

        assertThat(result.action()).isEqualTo(TradeAction.BUY);
        assertThat(result.emaScore()).isEqualTo(0.75);
    }

    @Test
    @DisplayName("임계치 미달 emaScore이면 HOLD action이 반환된다")
    void 임계치_미달이면_HOLD_반환() {
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());
        given(emaService.process("NVDA", 0.85)).willReturn(0.3);

        ProcessedSignal result = signalService.processSignal(signal);

        assertThat(result.action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("MANUAL 모드이면 emaScore에 관계없이 HOLD가 반환된다")
    void MANUAL_모드이면_HOLD_반환() {
        given(mockSettings.getTradingMode()).willReturn(TradingMode.MANUAL);
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());
        given(emaService.process("NVDA", 0.85)).willReturn(0.9);

        ProcessedSignal result = signalService.processSignal(signal);

        assertThat(result.action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("쿨다운 중이면 HOLD가 반환되고 SignalHistory는 저장된다")
    void 쿨다운_중이면_HOLD_반환() {
        SignalHistory recentSignal = mockRecentSignal(LocalDateTime.now().minusMinutes(1));
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.of(recentSignal));
        given(emaService.process("NVDA", 0.85)).willReturn(0.9);

        ProcessedSignal result = signalService.processSignal(signal);

        assertThat(result.action()).isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("processSignal() 호출 시 SignalHistory가 저장된다")
    void processSignal_호출시_SignalHistory가_저장된다() {
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.empty());
        given(emaService.process("NVDA", 0.85)).willReturn(0.75);

        signalService.processSignal(signal);

        verify(signalHistoryRepository).save(any(SignalHistory.class));
    }

    @Test
    @DisplayName("쿨다운 만료 후 신호는 정상 처리된다")
    void 쿨다운_만료_후_신호는_정상처리된다() {
        SignalHistory oldSignal = mockRecentSignal(LocalDateTime.now().minusMinutes(10));
        given(signalHistoryRepository.findTop1ByUserIdAndTickerOrderByCreatedAtDesc(any(), anyString()))
                .willReturn(Optional.of(oldSignal));
        given(emaService.process("NVDA", 0.85)).willReturn(0.75);

        ProcessedSignal result = signalService.processSignal(signal);

        assertThat(result.action()).isEqualTo(TradeAction.BUY);
    }

    // --- 헬퍼 ---

    private TradingSignalMessage buildSignal(String ticker, double rawScore) {
        try {
            String json = """
                    {"ticker":"%s","raw_score":%s,"rationale":"test","text_chunk":"chunk","timestamp":1710000000}
                    """.formatted(ticker, rawScore);
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
