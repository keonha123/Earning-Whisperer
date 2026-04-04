package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.TradingMode;

/**
 * 포트폴리오 룰 엔진 — 순수 계산 로직 (Spring 의존 없음).
 *
 * 판단 우선순위:
 * 1. MANUAL 모드 → 항상 HOLD
 * 2. 쿨다운 중 → HOLD
 * 3. |emaScore| < emaThreshold → HOLD
 * 4. emaScore >= emaThreshold → BUY
 * 5. emaScore <= -emaThreshold → SELL
 */
public class RuleEngine {

    private RuleEngine() {}

    /**
     * @param emaScore      EMA 계산 결과 (-1.0 ~ +1.0)
     * @param emaThreshold  BUY/SELL 실행 임계치 (0.0 ~ 1.0)
     * @param mode          거래 모드
     * @param inCooldown    쿨다운 시간 내 중복 신호 여부
     * @return 최종 매매 결정
     */
    public static TradeAction evaluate(double emaScore, double emaThreshold,
                                       TradingMode mode, boolean inCooldown) {
        if (mode == TradingMode.MANUAL) {
            return TradeAction.HOLD;
        }
        if (inCooldown) {
            return TradeAction.HOLD;
        }
        if (Math.abs(emaScore) < emaThreshold) {
            return TradeAction.HOLD;
        }
        return emaScore >= emaThreshold ? TradeAction.BUY : TradeAction.SELL;
    }
}
