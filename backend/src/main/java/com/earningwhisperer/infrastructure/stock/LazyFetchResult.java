package com.earningwhisperer.infrastructure.stock;

/**
 * {@link LazyFetchService#ensureExists(String)} 의 단계별 결과 요약.
 *
 * <p>각 {@code *Fetched} boolean 은 "이번 호출이 새로 채운 데이터" 의 여부를 나타낸다 — 이미 적재되어
 * 있던 데이터에는 {@code false}. 각 {@code *Attempted} boolean 은 "이번 호출이 외부 fetch 를 시도했는지"
 * 를 나타낸다 — DB 에 이미 데이터가 있어 skip 한 단계는 false.
 *
 * <p>호출자(Phase 3 REST 컨트롤러)가 어떤 데이터가 채워졌는지 / 어떤 단계가 실패했는지 / 모든 시도가
 * 실패했는지 ({@link #allFailed()}) 판단해 응답 정책 결정에 활용한다.
 *
 * <p>예시:
 * <ul>
 *     <li>Stock / Meta / DailyBar / Earnings 모두 신규 적재 → 4개 fetched 전부 true</li>
 *     <li>Stock 만 존재했던 ticker 의 메타/일봉/어닝 신규 적재 → stockCreated=false, 나머지 true</li>
 *     <li>FMP profile 빈 결과 → stockCreated=true, profileMissing=true (placeholder Stock 등록)</li>
 *     <li>Sync service 가 throw → 해당 단계 fetched=false, attempted=true. {@link #allFailed()}
 *         로 모든 시도가 실패했는지 검증</li>
 * </ul>
 */
public record LazyFetchResult(
        String ticker,
        /** Stock 엔티티가 이번 호출에서 신규 등록되었는지. */
        boolean stockCreated,
        /** StockMeta 가 이번 호출에서 신규 적재되었는지. */
        boolean metaFetched,
        /** DailyBar 가 이번 호출에서 신규 적재되었는지 (1개 이상). */
        boolean dailyBarsFetched,
        /** EarningsResult 가 이번 호출에서 신규 적재되었는지 (1개 이상). */
        boolean earningsFetched,
        /**
         * FMP profile 응답이 빈 결과여서 Stock 신규 등록 시 placeholder(companyName=ticker, sector=null,
         * active=false) 로 영속화되었는지. {@code stockCreated=true} 일 때만 의미가 있다.
         */
        boolean profileMissing,
        /** Stock 미존재 → {@code createStock} 진입 시 true (성공/실패 무관). */
        boolean stockAttempted,
        /** StockMeta 미존재 → {@code stockMetaSyncService.syncTicker} 진입 시 true. */
        boolean metaAttempted,
        /** DailyBar 미존재 → {@code dailyBarSyncService.syncTicker} 진입 시 true. */
        boolean dailyBarsAttempted,
        /** EarningsResult 미존재 → {@code earningsResultSyncService.syncTicker} 진입 시 true. */
        boolean earningsAttempted
) {

    /** 어느 한 단계라도 신규 적재되었으면 true. 호출자가 partial 응답 여부 판단에 사용. */
    public boolean anyFetched() {
        return stockCreated || metaFetched || dailyBarsFetched || earningsFetched;
    }

    /**
     * 모든 외부 fetch 시도가 실패했는지 — Phase 3 컨트롤러가 503 vs 200 분기에 사용.
     *
     * <p>판정 기준:
     * <ul>
     *     <li>최소 한 단계라도 attempted = true (skip 만 한 케이스는 false)</li>
     *     <li>그리고 어떤 단계도 새로 적재하지 못함 ({@code !anyFetched()})</li>
     * </ul>
     *
     * <p>이미 DB 에 모든 데이터가 적재되어 있어 어떤 단계도 시도하지 않은 케이스는 "정상 캐시 hit" 이므로
     * {@code allFailed()=false} — 호출자는 DB 데이터로 정상 응답해야 한다.
     */
    public boolean allFailed() {
        boolean attempted = stockAttempted || metaAttempted || dailyBarsAttempted || earningsAttempted;
        return attempted && !anyFetched();
    }
}
