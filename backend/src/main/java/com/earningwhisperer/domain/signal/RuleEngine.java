package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.TradingMode;

/**
 * 포트폴리오 룰 엔진 — 순수 계산 로직 (Spring 의존 없음).
 *
 * 판단 우선순위:
 * 1. MANUAL 모드 → 항상 HOLD
 * 2. 쿨다운 중 → HOLD
 * 3. |aiScore| < aiScoreThreshold → HOLD
 * 4. aiScore >= aiScoreThreshold → BUY
 * 5. aiScore <= -aiScoreThreshold → SELL
 */
public class RuleEngine {

    private RuleEngine() {}

    /**
     * @param aiScore           AI 엔진이 보낸 최종 점수 (-1.0 ~ +1.0, 시계열 맥락 반영됨)
     * @param aiScoreThreshold  BUY/SELL 실행 임계치 (0.0 ~ 1.0)
     * @param mode              거래 모드
     * @param inCooldown        쿨다운 시간 내 중복 신호 여부
     * @return 최종 매매 결정
     */
    public static TradeAction evaluate(double aiScore, double aiScoreThreshold,
                                       TradingMode mode, boolean inCooldown) {
        if (mode == TradingMode.MANUAL) {
            return TradeAction.HOLD;
        }
        if (inCooldown) {
            return TradeAction.HOLD;
        }
        if (Math.abs(aiScore) < aiScoreThreshold) {
            return TradeAction.HOLD;
        }
        return aiScore >= aiScoreThreshold ? TradeAction.BUY : TradeAction.SELL;
    }
}
