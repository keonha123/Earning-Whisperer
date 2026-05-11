package com.earningwhisperer.infrastructure.fmp;

/**
 * FMP 일일/분당 호출 한도 초과 시 throw.
 *
 * <p>호출자는 본 예외를 잡아 graceful fallback(예: 빈 결과 반환, 재시도 큐 적재 등)을 수행한다.
 * unchecked 로 정의하여 호출 측 boilerplate 를 최소화한다.
 */
public class RateLimitExceededException extends RuntimeException {

    public RateLimitExceededException(String message) {
        super(message);
    }

    public RateLimitExceededException(String message, Throwable cause) {
        super(message, cause);
    }
}
