package com.earningwhisperer.global.common;

import com.earningwhisperer.infrastructure.finnhub.FinnhubRateLimiter;
import com.earningwhisperer.infrastructure.fmp.FmpRateLimiter;

/**
 * 외부 데이터 동기화의 우선순위.
 *
 * <p>FMP / Finnhub rate limiter 가 각각 자기 enum (FmpRateLimiter.Priority,
 * FinnhubRateLimiter.Priority) 을 가지지만, 동기화 service 시그니처에 vendor 별 enum 이
 * 직접 노출되면 호출자(LazyFetchService / Scheduler)가 두 enum 을 동시에 다뤄야 해서
 * 경계가 새는 느낌이 든다. 본 도메인-중립 enum 으로 통합하고 각 service 가 내부에서
 * vendor enum 으로 매핑한다.
 *
 * <p>위치: {@code global/common/} ({@code BaseEntity} 옆) — 도메인 어휘에 묶이지 않는
 * 횡단 관심사.
 */
public enum SyncPriority {

    /** 사용자 trigger lazy fetch — 즉시 응답 필요. RateLimiter 큐에서 먼저 drain 된다. */
    HIGH,

    /** 사전 동기화 batch — 백그라운드 처리. 사용자 trigger 와 경합 시 양보. */
    LOW;

    /** FMP rate limiter 의 자체 Priority enum 으로 매핑. */
    public FmpRateLimiter.Priority toFmp() {
        return this == HIGH ? FmpRateLimiter.Priority.HIGH : FmpRateLimiter.Priority.LOW;
    }

    /** Finnhub rate limiter 의 자체 Priority enum 으로 매핑. */
    public FinnhubRateLimiter.Priority toFinnhub() {
        return this == HIGH ? FinnhubRateLimiter.Priority.HIGH : FinnhubRateLimiter.Priority.LOW;
    }
}
