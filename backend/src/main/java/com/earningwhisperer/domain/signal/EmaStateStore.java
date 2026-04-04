package com.earningwhisperer.domain.signal;

import java.util.Optional;

/**
 * ticker별 현재 EMA 값을 저장/조회하는 상태 저장소 인터페이스.
 *
 * 현재 구현체: InMemoryEmaStateStore (ConcurrentHashMap)
 * 추후 구현체: RedisEmaStateStore (분산 환경 대응 시 교체)
 */
public interface EmaStateStore {

    /**
     * ticker의 현재 EMA 값을 조회한다.
     * 첫 번째 신호라면 값이 없으므로 empty를 반환한다.
     */
    Optional<Double> findByTicker(String ticker);

    /**
     * ticker의 EMA 값을 저장한다.
     */
    void save(String ticker, double emaScore);
}
