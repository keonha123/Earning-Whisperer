package com.earningwhisperer.infrastructure.finnhub;

/**
 * {@link PriceReactionCalculatorService#computeAndUpdate} 의 결과 분류.
 *
 * <p>운영 모니터링에서 "재시도 의미 있음" vs "데이터 오류로 영구 제외 가치" 를 구분 가능하게 한다.
 * boolean 반환은 둘을 합쳐 silent 가 되므로 enum 으로 나눈다.
 */
public enum PriceReactionResult {

    /** 정상 계산 + 영속화. */
    COMPUTED,

    /**
     * 일봉 부족(윈도 내 2개 미만, before/after 없음, after close null) — 일시적.
     * DailyBarSync 가 다음 사이클에서 채우면 재시도 가능.
     */
    DATA_MISSING,

    /**
     * 데이터 오류(before close ≤ 0, 가격반응 한도 초과) — 재시도해도 동일 결과.
     * 운영자가 source 데이터를 점검할 가치가 있다.
     */
    DATA_ERROR
}
