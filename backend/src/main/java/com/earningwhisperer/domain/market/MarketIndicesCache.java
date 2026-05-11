package com.earningwhisperer.domain.market;

import com.earningwhisperer.infrastructure.redis.MarketIndicesMessage;
import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 5종 시장 지수의 최신 스냅샷을 메모리에 보관하는 인메모리 캐시.
 *
 * - 단일 인스턴스 (싱글톤 빈)
 * - {@link ConcurrentHashMap} 사용으로 다중 구독자/요청 동시성 안전
 * - 같은 symbol 재발행 시 최신 값으로 덮어쓴다.
 * - REST GET /api/v1/market/indices 응답의 단일 진실 공급원.
 *
 * 영속성은 의도적으로 두지 않는다. 1분 단위 스트림이라 서버 재시작 시
 * 다음 발행 사이클(최대 1분)에 자연스럽게 재충전된다.
 */
@Component
public class MarketIndicesCache {

    private final ConcurrentHashMap<String, MarketIndexSnapshot> snapshots = new ConcurrentHashMap<>();

    /**
     * 신규/갱신 메시지를 캐시에 반영한다.
     * 미지원 심볼은 호출자가 사전에 드롭하므로 여기서는 검증하지 않는다.
     */
    public MarketIndexSnapshot put(MarketIndicesMessage message) {
        MarketIndexSnapshot snapshot = MarketIndexSnapshot.from(message);
        snapshots.put(snapshot.symbol(), snapshot);
        return snapshot;
    }

    /**
     * 보유 중인 모든 스냅샷을 symbol 알파벳 오름차순으로 정렬해 반환한다.
     * 캐시가 비어 있으면 빈 리스트를 반환한다.
     */
    public List<MarketIndexSnapshot> getAll() {
        return snapshots.values().stream()
                .sorted(Comparator.comparing(MarketIndexSnapshot::symbol))
                .toList();
    }
}
