package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.TradingMode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("RuleEngine 단위 테스트")
class RuleEngineTest {

    private static final double THRESHOLD = 0.6;

    @Test
    @DisplayName("MANUAL 모드이면 emaScore에 관계없이 항상 HOLD를 반환한다")
    void MANUAL_모드이면_항상_HOLD() {
        assertThat(RuleEngine.evaluate(0.9, THRESHOLD, TradingMode.MANUAL, false))
                .isEqualTo(TradeAction.HOLD);
        assertThat(RuleEngine.evaluate(-0.9, THRESHOLD, TradingMode.MANUAL, false))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("쿨다운 중이면 emaScore에 관계없이 HOLD를 반환한다")
    void 쿨다운_중이면_HOLD() {
        assertThat(RuleEngine.evaluate(0.9, THRESHOLD, TradingMode.AUTO_PILOT, true))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("emaScore가 임계치 미만이면 HOLD를 반환한다")
    void emaScore가_임계치_미만이면_HOLD() {
        assertThat(RuleEngine.evaluate(0.5, THRESHOLD, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.HOLD);
        assertThat(RuleEngine.evaluate(-0.5, THRESHOLD, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("emaScore가 임계치 이상이면 BUY를 반환한다")
    void emaScore가_임계치_이상이면_BUY() {
        assertThat(RuleEngine.evaluate(0.6, THRESHOLD, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.BUY);
        assertThat(RuleEngine.evaluate(1.0, THRESHOLD, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.BUY);
    }

    @Test
    @DisplayName("emaScore가 음수 임계치 이하이면 SELL을 반환한다")
    void emaScore가_음수임계치_이하이면_SELL() {
        assertThat(RuleEngine.evaluate(-0.6, THRESHOLD, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.SELL);
        assertThat(RuleEngine.evaluate(-1.0, THRESHOLD, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.SELL);
    }

    @Test
    @DisplayName("SEMI_AUTO 모드도 동일한 임계치 룰을 적용한다")
    void SEMI_AUTO_모드도_임계치_룰을_적용한다() {
        assertThat(RuleEngine.evaluate(0.8, THRESHOLD, TradingMode.SEMI_AUTO, false))
                .isEqualTo(TradeAction.BUY);
        assertThat(RuleEngine.evaluate(0.3, THRESHOLD, TradingMode.SEMI_AUTO, false))
                .isEqualTo(TradeAction.HOLD);
    }

    @Test
    @DisplayName("임계치가 0이면 emaScore != 0인 모든 신호가 BUY 또는 SELL이 된다")
    void 임계치가_0이면_모든신호가_BUY_또는_SELL() {
        assertThat(RuleEngine.evaluate(0.01, 0.0, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.BUY);
        assertThat(RuleEngine.evaluate(-0.01, 0.0, TradingMode.AUTO_PILOT, false))
                .isEqualTo(TradeAction.SELL);
    }
}
