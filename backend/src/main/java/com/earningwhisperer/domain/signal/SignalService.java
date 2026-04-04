package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.infrastructure.redis.TradingSignalMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/**
 * 수신된 AI 신호를 종합 처리하는 서비스.
 *
 * 처리 흐름:
 * 1. 포트폴리오 설정 조회 (emaThreshold, cooldownMinutes, tradingMode)
 * 2. 쿨다운 체크 — 동일 종목의 직전 신호가 cooldownMinutes 이내이면 HOLD
 * 3. EmaService로 EMA 계산
 * 4. RuleEngine으로 BUY/SELL/HOLD 결정
 * 5. SignalHistory DB 저장
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SignalService {

    // Phase 4: 인증 미구현 — 시스템 기본 사용자 ID 고정
    static final Long SYSTEM_USER_ID = 1L;

    private final EmaService emaService;
    private final PortfolioSettingsService portfolioSettingsService;
    private final SignalHistoryRepository signalHistoryRepository;
    private final UserRepository userRepository;

    @Transactional
    public ProcessedSignal processSignal(TradingSignalMessage signal) {
        PortfolioSettings settings = portfolioSettingsService.getSettings(SYSTEM_USER_ID);

        boolean inCooldown = isInCooldown(signal.getTicker(), settings.getCooldownMinutes());

        double emaScore = emaService.process(signal.getTicker(), signal.getRawScore());

        TradeAction action = RuleEngine.evaluate(
                emaScore, settings.getEmaThreshold(), settings.getTradingMode(), inCooldown);

        saveSignalHistory(signal, emaScore, action);

        log.info("[SignalService] ticker={} emaScore={} action={}", signal.getTicker(), emaScore, action);
        return new ProcessedSignal(emaScore, action);
    }

    private boolean isInCooldown(String ticker, int cooldownMinutes) {
        return signalHistoryRepository
                .findTop1ByUserIdAndTickerOrderByCreatedAtDesc(SYSTEM_USER_ID, ticker)
                .map(last -> last.getCreatedAt().isAfter(
                        LocalDateTime.now().minusMinutes(cooldownMinutes)))
                .orElse(false);
    }

    private void saveSignalHistory(TradingSignalMessage signal, double emaScore, TradeAction action) {
        User user = userRepository.findById(SYSTEM_USER_ID)
                .orElseThrow(() -> new IllegalStateException("시스템 사용자(id=1)가 존재하지 않습니다."));

        SignalHistory history = SignalHistory.builder()
                .user(user)
                .ticker(signal.getTicker())
                .rawScore(signal.getRawScore())
                .emaScore(emaScore)
                .rationale(signal.getRationale())
                .textChunk(signal.getTextChunk())
                .action(action)
                .signalTimestamp(signal.getTimestamp())
                .build();

        signalHistoryRepository.save(history);
    }
}
