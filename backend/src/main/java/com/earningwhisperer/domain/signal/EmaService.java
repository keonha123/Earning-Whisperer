package com.earningwhisperer.domain.signal;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * EMA 계산의 전체 흐름을 조율하는 서비스.
 *
 * 1. EmaStateStore에서 ticker의 직전 EMA 조회
 * 2. 첫 번째 신호이면 rawScore를 초기값으로 사용
 * 3. EmaCalculator로 새 EMA 계산
 * 4. EmaStateStore에 결과 저장 후 반환
 */
@Service
@RequiredArgsConstructor
public class EmaService {

    private final EmaStateStore emaStateStore;

    @Value("${ema.window-size:10}")
    private int windowSize;

    /**
     * rawScore를 수신하여 EMA를 계산하고 저장한 뒤 결과를 반환한다.
     *
     * @param ticker   종목 심볼 (예: "NVDA")
     * @param rawScore AI가 도출한 원시 감성 점수 (-1.0 ~ +1.0)
     * @return 계산된 ema_score
     */
    public double process(String ticker, double rawScore) {
        double prevEma = emaStateStore.findByTicker(ticker)
                .orElse(rawScore); // 첫 신호: prevEma = rawScore → ema 변동 없음

        double newEma = EmaCalculator.calculate(rawScore, prevEma, windowSize);
        emaStateStore.save(ticker, newEma);
        return newEma;
    }
}
