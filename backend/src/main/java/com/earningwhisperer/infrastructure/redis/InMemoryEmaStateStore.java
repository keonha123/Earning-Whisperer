package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.EmaStateStore;
import org.springframework.stereotype.Component;

import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * EmaStateStore의 인메모리 구현체.
 *
 * ConcurrentHashMap으로 멀티스레드 환경에서 안전하게 ticker별 EMA 상태를 관리한다.
 * 서버 재시작 시 상태가 초기화되며, 분산 환경이 필요해지면 RedisEmaStateStore로 교체한다.
 */
@Component
public class InMemoryEmaStateStore implements EmaStateStore {

    private final ConcurrentHashMap<String, Double> store = new ConcurrentHashMap<>();

    @Override
    public Optional<Double> findByTicker(String ticker) {
        return Optional.ofNullable(store.get(ticker));
    }

    @Override
    public void save(String ticker, double emaScore) {
        store.put(ticker, emaScore);
    }
}
