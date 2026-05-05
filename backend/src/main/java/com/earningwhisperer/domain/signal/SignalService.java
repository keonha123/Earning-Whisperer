package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.BrokerAccount;
import com.earningwhisperer.domain.portfolio.BrokerAccountService;
import com.earningwhisperer.domain.portfolio.PortfolioSettings;
import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.PositionService;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.infrastructure.redis.TradingSignalMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * 수신된 AI 신호를 전체 사용자에게 팬아웃 처리하는 서비스.
 *
 * 처리 흐름:
 * 1. 전체 사용자 PortfolioSettings 일괄 조회
 * 2. 사용자별: 활성 BrokerAccount 확인 → 쿨다운 체크 → RuleEngine 평가 → SignalHistory 생성
 * 3. SignalHistory batch 저장
 *
 * 활성 BrokerAccount 가 없으면 fail-safe HOLD — 사용자가 모드를 활성화하기 전까지는 거래가 일어나지 않음.
 * AI 엔진이 시계열 맥락까지 반영한 최종 점수(aiScore)를 보내주므로 백엔드는 평활화 없이 직접 평가한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SignalService {

    private final PortfolioSettingsService portfolioSettingsService;
    private final PositionService positionService;
    private final BrokerAccountService brokerAccountService;
    private final SignalHistoryRepository signalHistoryRepository;

    @Transactional
    public List<UserProcessedSignal> processSignalForAllUsers(TradingSignalMessage signal) {
        double aiScore = signal.getAiScore();

        List<PortfolioSettings> allSettings = portfolioSettingsService.getAllSettings();

        List<UserProcessedSignal> results = new ArrayList<>();
        List<SignalHistory> histories = new ArrayList<>();

        for (PortfolioSettings settings : allSettings) {
            try {
                User user = settings.getUser();

                boolean inCooldown = isInCooldown(
                        user.getId(), signal.getTicker(), settings.getCooldownMinutes());

                Double ratio = settings.getBuyAmountRatio();
                if (ratio == null || ratio <= 0 || ratio > 1) {
                    log.warn("[SignalService] buyAmountRatio 이상 — userId={} ratio={}, 건너뜀",
                            user.getId(), ratio);
                    continue;
                }

                Double maxPositionRatio = settings.getMaxPositionRatio();
                if (maxPositionRatio == null || maxPositionRatio <= 0) {
                    maxPositionRatio = 1.0;
                }

                // 활성 BrokerAccount 확인. 없으면 사용자 자체가 활성화 안 된 상태 — SignalHistory 도
                // 기록하지 않고 result 만 HOLD/null 로 반환 (DB 노이즈 + 쿨다운 영향 방지).
                Optional<BrokerAccount> activeOpt = brokerAccountService.getActive(user.getId());
                if (activeOpt.isEmpty()) {
                    log.debug("[SignalService] 활성 BrokerAccount 미설정 — skip userId={}", user.getId());
                    results.add(new UserProcessedSignal(
                            user, null, TradeAction.HOLD, aiScore, settings.getTradingMode(), ratio));
                    continue;
                }

                BrokerAccount active = activeOpt.get();
                Double cashBalance = active.getCashBalance();

                TradeAction action;
                if (cashBalance == null || cashBalance <= 0) {
                    log.info("[SignalService] cashBalance 미동기화/0 — fail-safe HOLD userId={} brokerAccountId={}",
                            user.getId(), active.getId());
                    action = TradeAction.HOLD;
                } else {
                    double currentPositionRatio = positionService.computeBookRatio(
                            active.getId(), signal.getTicker(), cashBalance);

                    action = RuleEngine.evaluate(
                            aiScore, settings.getAiScoreThreshold(), settings.getTradingMode(), inCooldown,
                            currentPositionRatio, ratio, maxPositionRatio);
                }

                SignalHistory history = SignalHistory.builder()
                        .user(user)
                        .ticker(signal.getTicker())
                        .aiScore(aiScore)
                        .rationale(signal.getRationale())
                        .textChunk(signal.getTextChunk())
                        .action(action)
                        .signalTimestamp(signal.getTimestamp())
                        .build();
                histories.add(history);

                results.add(new UserProcessedSignal(
                        user, active.getId(), action, aiScore, settings.getTradingMode(), ratio));
            } catch (Exception e) {
                Long userId = settings.getUser() != null ? settings.getUser().getId() : null;
                log.error("[SignalService] 사용자별 처리 실패 - userId={} ticker={}",
                        userId, signal.getTicker(), e);
            }
        }

        if (!histories.isEmpty()) {
            signalHistoryRepository.saveAll(histories);
        }

        log.info("[SignalService] ticker={} aiScore={} 처리 사용자 수={}",
                signal.getTicker(), aiScore, results.size());
        return results;
    }

    private boolean isInCooldown(Long userId, String ticker, int cooldownMinutes) {
        return signalHistoryRepository
                .findTop1ByUserIdAndTickerOrderByCreatedAtDesc(userId, ticker)
                .map(last -> last.getCreatedAt().isAfter(
                        LocalDateTime.now().minusMinutes(cooldownMinutes)))
                .orElse(false);
    }
}
