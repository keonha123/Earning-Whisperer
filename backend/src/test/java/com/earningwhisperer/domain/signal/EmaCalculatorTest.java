package com.earningwhisperer.domain.signal;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.within;

@DisplayName("EmaCalculator 단위 테스트")
class EmaCalculatorTest {

    private static final int DEFAULT_WINDOW = 10;
    // alpha = 2 / (10 + 1) ≈ 0.1818...
    private static final double ALPHA = 2.0 / (DEFAULT_WINDOW + 1);
    private static final double TOLERANCE = 1e-10;

    @Test
    @DisplayName("첫 번째 신호: prevEma == rawScore이면 결과도 rawScore와 같다")
    void 첫번째_신호_prevEma가_rawScore와_같으면_결과도_동일하다() {
        double rawScore = 0.85;

        double result = EmaCalculator.calculate(rawScore, rawScore, DEFAULT_WINDOW);

        assertThat(result).isCloseTo(rawScore, within(TOLERANCE));
    }

    @Test
    @DisplayName("두 번째 신호: alpha * rawScore + (1 - alpha) * prevEma 공식이 적용된다")
    void 두번째_신호_EMA_공식이_올바르게_적용된다() {
        double rawScore = 0.85;
        double prevEma  = 0.50;
        double expected = ALPHA * rawScore + (1 - ALPHA) * prevEma;

        double result = EmaCalculator.calculate(rawScore, prevEma, DEFAULT_WINDOW);

        assertThat(result).isCloseTo(expected, within(TOLERANCE));
    }

    @Test
    @DisplayName("강한 매수 신호를 반복 수신하면 EMA가 rawScore에 점진적으로 수렴한다")
    void 강한_매수_신호_반복시_EMA가_rawScore에_수렴한다() {
        double rawScore = 1.0;
        double ema = 0.0;

        for (int i = 0; i < 100; i++) {
            ema = EmaCalculator.calculate(rawScore, ema, DEFAULT_WINDOW);
        }

        // 100번 반복 후 EMA는 1.0에 근접해야 함
        assertThat(ema).isGreaterThan(0.99);
    }

    @Test
    @DisplayName("강한 매도 신호를 반복 수신하면 EMA가 -1.0에 점진적으로 수렴한다")
    void 강한_매도_신호_반복시_EMA가_음수에_수렴한다() {
        double rawScore = -1.0;
        double ema = 0.0;

        for (int i = 0; i < 100; i++) {
            ema = EmaCalculator.calculate(rawScore, ema, DEFAULT_WINDOW);
        }

        assertThat(ema).isLessThan(-0.99);
    }

    @Test
    @DisplayName("windowSize가 클수록 EMA가 rawScore 변화에 더 둔감하다")
    void windowSize가_클수록_EMA_변화가_둔감하다() {
        double rawScore = 1.0;
        double prevEma  = 0.0;

        double emaSmallWindow = EmaCalculator.calculate(rawScore, prevEma, 5);
        double emaLargeWindow = EmaCalculator.calculate(rawScore, prevEma, 20);

        // 윈도우가 작을수록 alpha가 커서 rawScore에 더 빠르게 반응
        assertThat(emaSmallWindow).isGreaterThan(emaLargeWindow);
    }

    @Test
    @DisplayName("windowSize가 0 이하이면 IllegalArgumentException을 던진다")
    void windowSize가_0이하이면_예외가_발생한다() {
        assertThatThrownBy(() -> EmaCalculator.calculate(0.5, 0.5, 0))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("windowSize");
    }

    @Test
    @DisplayName("경계값: rawScore = +1.0 과 prevEma = -1.0 의 합성 결과는 유효 범위 내에 있다")
    void 경계값_rawScore와_prevEma_극단값_조합시_결과가_유효범위내에_있다() {
        double result = EmaCalculator.calculate(1.0, -1.0, DEFAULT_WINDOW);

        assertThat(result).isBetween(-1.0, 1.0);
    }
}
