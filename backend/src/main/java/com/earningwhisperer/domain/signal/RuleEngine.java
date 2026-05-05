package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.TradingMode;

/**
 * 포트폴리오 룰 엔진 — 순수 계산 로직 (Spring 의존 없음).
 *
 * 판단 우선순위:
 * 1. MANUAL 모드 → 항상 HOLD
 * 2. 쿨다운 중 → HOLD
 * 3. |aiScore| &lt; aiScoreThreshold → HOLD
 * 4. SELL 시그널 (aiScore ≤ -threshold) → SELL
 * 5. BUY 시그널 (aiScore ≥ threshold) 인데 매수 후 비중이 maxPositionRatio 초과 예상 → HOLD
 * 6. 그 외 BUY → BUY
 */
public class RuleEngine {

    /** 부동소수점 누적 오차 흡수용 epsilon — 사용자 설정값(예: 0.30) 정확히 도달 시 BUY 허용. */
    private static final double RATIO_EPSILON = 1e-9;

    private RuleEngine() {}

    /**
     * @param aiScore               AI 엔진이 보낸 최종 점수 (-1.0 ~ +1.0)
     * @param aiScoreThreshold      BUY/SELL 실행 임계치 (0.0 ~ 1.0)
     * @param mode                  거래 모드
     * @param inCooldown            쿨다운 시간 내 중복 신호 여부
     * @param currentPositionRatio  ticker 의 현재 보유 비중 (매수 기준, 0.0 ~ 1.0). PositionService 가 산출
     * @param buyAmountRatio        1회 매수 시 예수금 사용 비율 (PortfolioSettings)
     * @param maxPositionRatio      ticker 최대 보유 비중 한도 (PortfolioSettings)
     * @return 최종 매매 결정
     */
    public static TradeAction evaluate(double aiScore, double aiScoreThreshold,
                                       TradingMode mode, boolean inCooldown,
                                       double currentPositionRatio,
                                       double buyAmountRatio,
                                       double maxPositionRatio) {
        if (mode == TradingMode.MANUAL) {
            return TradeAction.HOLD;
        }
        if (inCooldown) {
            return TradeAction.HOLD;
        }
        if (Math.abs(aiScore) < aiScoreThreshold) {
            return TradeAction.HOLD;
        }
        if (aiScore <= -aiScoreThreshold) {
            return TradeAction.SELL;
        }
        // BUY 분기 — 매수 후 예상 비중이 한도를 초과하면 HOLD (epsilon 흡수로 0.20+0.10=0.30 케이스 BUY 허용)
        if (currentPositionRatio + buyAmountRatio > maxPositionRatio + RATIO_EPSILON) {
            return TradeAction.HOLD;
        }
        return TradeAction.BUY;
    }
}
