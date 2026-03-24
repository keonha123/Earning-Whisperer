package com.earningwhisperer.domain.signal;

/**
 * EMA(지수이동평균) 순수 계산 유틸리티.
 *
 * 상태를 갖지 않으므로 어디서든 직접 호출 가능하며 단위 테스트가 용이하다.
 *
 * 공식:
 *   alpha     = 2.0 / (windowSize + 1)
 *   ema_score = alpha * rawScore + (1 - alpha) * prevEma
 */
public class EmaCalculator {

    private EmaCalculator() {}

    /**
     * EMA 점수를 계산한다.
     *
     * @param rawScore   AI가 도출한 원시 감성 점수 (-1.0 ~ +1.0)
     * @param prevEma    직전 EMA 값 (첫 번째 신호인 경우 rawScore와 동일한 값을 전달)
     * @param windowSize EMA 윈도우 크기 (클수록 변동에 둔감, 기본값 10)
     * @return 계산된 EMA 점수
     */
    public static double calculate(double rawScore, double prevEma, int windowSize) {
        if (windowSize <= 0) {
            throw new IllegalArgumentException("windowSize는 1 이상이어야 합니다. windowSize=" + windowSize);
        }
        double alpha = 2.0 / (windowSize + 1);
        return alpha * rawScore + (1 - alpha) * prevEma;
    }
}
