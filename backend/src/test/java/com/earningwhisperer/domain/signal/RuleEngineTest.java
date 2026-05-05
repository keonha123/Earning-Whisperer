package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.TradingMode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("RuleEngine 단위 테스트")
class RuleEngineTest {

    private static final double THRESHOLD = 0.6;
    private static final double DEFAULT_BUY_RATIO = 0.1;
    private static final double NO_LIMIT_MAX_RATIO = 1.0;
    private static final double ZERO_HOLDING = 0.0;

    /** maxPositionRatio 가드를 끈 evaluate (기존 룰 회귀 보호용). */
    private static TradeAction evalNoMaxGuard(double aiScore, TradingMode mode, boolean inCooldown) {
        return RuleEngine.evaluate(aiScore, THRESHOLD, mode, inCooldown,
                ZERO_HOLDING, DEFAULT_BUY_RATIO, NO_LIMIT_MAX_RATIO);
    }

    @Test
    @DisplayName("MANUAL 모드이면 aiScore에 관계없이 항상 HOLD를 반환한다")
    void MANUAL_모드이면_항상_HOLD() {
        assertThat(evalNoMaxGuard(0.9, TradingMode.MANUAL, false))
                .isEqualTo(TradeAction.HOLD);
        assertThat(evalNoMaxGuard(-0.9, TradingMode.MANUAL, false))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("쿨다운 중이면 aiScore에 관계없이 HOLD를 반환한다")
    void 쿨다운_중이면_HOLD() {
        assertThat(evalNoMaxGuard(0.9, TradingMode.AUTO_PILOT, true))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("aiScore가 임계치 미만이면 HOLD를 반환한다")
    void aiScore가_임계치_미만이면_HOLD() {
        assertThat(evalNoMaxGuard(0.5, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.HOLD);
        assertThat(evalNoMaxGuard(-0.5, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("aiScore가 임계치 이상이면 BUY를 반환한다")
    void aiScore가_임계치_이상이면_BUY() {
        assertThat(evalNoMaxGuard(0.6, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.BUY);
        assertThat(evalNoMaxGuard(1.0, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.BUY);
    }

    @Test
    @DisplayName("aiScore가 음수 임계치 이하이면 SELL을 반환한다")
    void aiScore가_음수임계치_이하이면_SELL() {
        assertThat(evalNoMaxGuard(-0.6, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.SELL);
        assertThat(evalNoMaxGuard(-1.0, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("SEMI_AUTO 모드도 동일한 임계치 룰을 적용한다")
    void SEMI_AUTO_모드도_임계치_룰을_적용한다() {
        assertThat(evalNoMaxGuard(0.8, TradingMode.SEMI_AUTO, false))
                .isEqualTo(TradeAction.BUY);
        assertThat(evalNoMaxGuard(0.3, TradingMode.SEMI_AUTO, false))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("임계치가 0이면 aiScore != 0인 모든 신호가 BUY 또는 SELL이 된다")
    void 임계치가_0이면_모든신호가_BUY_또는_SELL() {
        assertThat(RuleEngine.evaluate(0.01, 0.0, TradingMode.AUTO_PILOT, false,
                ZERO_HOLDING, DEFAULT_BUY_RATIO, NO_LIMIT_MAX_RATIO))
                .isEqualTo(TradeAction.BUY);
        assertThat(RuleEngine.evaluate(-0.01, 0.0, TradingMode.AUTO_PILOT, false,
                ZERO_HOLDING, DEFAULT_BUY_RATIO, NO_LIMIT_MAX_RATIO))
                .isEqualTo(TradeAction.SELL);
    }

    // --- maxPositionRatio 가드 신규 룰 ---

    @Test
    @DisplayName("BUY 시그널이지만 매수 후 비중이 maxPositionRatio 를 초과하면 HOLD")
    void BUY_매수후_비중_초과면_HOLD() {
        // 현재 비중 0.25 + buyRatio 0.1 = 0.35 > maxRatio 0.30
        assertThat(RuleEngine.evaluate(0.9, THRESHOLD, TradingMode.AUTO_PILOT, false,
                0.25, 0.10, 0.30))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("BUY 시그널이고 매수 후 비중이 한도 이내면 BUY")
    void BUY_매수후_비중_한도이내면_BUY() {
        // 0.15 + 0.10 = 0.25 < 0.30 (한도 이내)
        assertThat(RuleEngine.evaluate(0.9, THRESHOLD, TradingMode.AUTO_PILOT, false,
                0.15, 0.10, 0.30))
                .isEqualTo(TradeAction.BUY);
    }

    @Test
    @DisplayName("SELL 시그널은 maxPositionRatio 가드 무관하게 SELL")
    void SELL은_비중가드_미적용() {
        // 비중이 한도 도달이어도 SELL 은 통과 (포지션 정리는 자유)
        assertThat(RuleEngine.evaluate(-0.9, THRESHOLD, TradingMode.AUTO_PILOT, false,
                0.50, 0.10, 0.30))
                .isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("미보유 ticker (currentPositionRatio=0) 면 매수 비율이 한도 이하면 BUY")
    void 미보유_ticker는_buyRatio가_한도이하면_BUY() {
        assertThat(RuleEngine.evaluate(0.9, THRESHOLD, TradingMode.AUTO_PILOT, false,
                0.0, 0.10, 0.30))
                .isEqualTo(TradeAction.BUY);
    }

    @Test
    @DisplayName("0.20 + 0.10 = 0.30 (부동소수점 누적 오차) 도 한도 정확히 도달은 BUY 허용 (epsilon)")
    void epsilon_경계_BUY_허용() {
        // 부동소수점에서 0.20 + 0.10 = 0.30000000000000004 이지만 epsilon 으로 흡수
        assertThat(RuleEngine.evaluate(0.9, THRESHOLD, TradingMode.AUTO_PILOT, false,
                0.20, 0.10, 0.30))
                .isEqualTo(TradeAction.BUY);
    }
}
