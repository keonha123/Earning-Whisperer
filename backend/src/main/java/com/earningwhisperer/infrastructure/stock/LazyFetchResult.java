package com.earningwhisperer.infrastructure.stock;

/**
 * {@link LazyFetchService#ensureExists(String)} 의 단계별 결과 요약.
 *
 * <p>각 boolean 은 "이번 호출이 새로 채운 데이터" 의 여부를 나타낸다 — 이미 적재되어 있던 데이터에는
 * {@code false}. 호출자(Phase 3 REST 컨트롤러)가 어떤 데이터가 채워졌는지 / 어떤 단계가 실패했는지
 * 판단해 응답 정책 결정에 활용한다.
 *
 * <p>예시:
 * <ul>
 *     <li>Stock / Meta / DailyBar / Earnings 모두 신규 적재 → 4개 boolean 전부 true</li>
 *     <li>Stock 만 존재했던 ticker 의 메타/일봉/어닝 신규 적재 → stockCreated=false, 나머지 true</li>
 *     <li>FMP profile 빈 결과 → stockCreated=true, profileMissing=true (placeholder Stock 등록)</li>
 *     <li>Sync service 가 throw → 해당 단계 false. {@link #anyFetched()} 로 partial 검증</li>
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
        boolean profileMissing
) {

    /** 어느 한 단계라도 신규 적재되었으면 true. 호출자가 partial 응답 여부 판단에 사용. */
    public boolean anyFetched() {
        return stockCreated || metaFetched || dailyBarsFetched || earningsFetched;
    }
}
