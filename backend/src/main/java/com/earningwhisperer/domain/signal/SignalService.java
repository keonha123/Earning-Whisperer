package com.earningwhisperer.domain.signal;

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

/**
 * 수신된 AI 신호를 전체 사용자에게 팬아웃 처리하는 서비스.
 *
 * 처리 흐름:
 * 1. 전체 사용자 PortfolioSettings 일괄 조회
 * 2. 사용자별: 쿨다운 체크 → RuleEngine 평가 → SignalHistory 생성
 * 3. SignalHistory batch 저장
 *
 * AI 엔진이 시계열 맥락까지 반영한 최종 점수(aiScore)를 보내주므로 백엔드는 평활화 없이 직접 평가한다.
 * 개별 사용자 처리 실패 시 해당 사용자만 건너뛰고 나머지는 정상 처리된다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SignalService {

    private final PortfolioSettingsService portfolioSettingsService;
    private final PositionService positionService;
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
                    // 설정 누락 — 비중 검증을 우회하지 않도록 1.0 으로 처리 (즉 검증 실효화 X)
                    // 정책상 PortfolioSettings 생성 시 NOT NULL 이므로 운영에선 거의 발생 안 함.
                    maxPositionRatio = 1.0;
                }

                // cashBalance 가 null 이면 KIS 첫 sync 미완료 — currentPositionRatio 산출 불가.
                // BUY 가 무제한 통과되어 maxPositionRatio 가드가 무력화되는 사고를 막기 위해
                // 신호 자체를 HOLD 로 강제 (fail-safe). SELL 도 보유 정보 없이 진행하면 위험하므로 동일.
                Double cashBalance = settings.getCashBalance();
                TradeAction action;
                if (cashBalance == null || cashBalance < 0) {
                    log.info("[SignalService] cashBalance 미동기화 — fail-safe HOLD userId={}", user.getId());
                    action = TradeAction.HOLD;
                } else {
                    double currentPositionRatio = positionService.computeBookRatio(
                            user.getId(), signal.getTicker(), cashBalance);

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
                        user, action, aiScore, settings.getTradingMode(), ratio));
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
