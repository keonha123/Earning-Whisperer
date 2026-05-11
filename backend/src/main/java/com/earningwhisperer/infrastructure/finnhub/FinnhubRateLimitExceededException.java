package com.earningwhisperer.infrastructure.finnhub;

/**
 * Finnhub rate limiter 의 dispose / interrupt 등 비정상 종료 시 throw.
 *
 * <p>Finnhub 무료 티어는 분당 60 calls 제한 외에 명시적 일일 한도가 없어 정상 호출 경로에서는
 * 이 예외가 발생하지 않는다. {@link FinnhubRateLimiter} 가 shutdown 되거나 wait 가 interrupt 된
 * 경우에만 예외가 사용된다.
 *
 * <p>FMP 측의 {@code RateLimitExceededException} 과 동일한 unchecked 시그니처를 갖지만 패키지를
 * 분리하여 패키지 결합도를 낮춘다.
 */
public class FinnhubRateLimitExceededException extends RuntimeException {

    public FinnhubRateLimitExceededException(String message) {
        super(message);
    }

    public FinnhubRateLimitExceededException(String message, Throwable cause) {
        super(message, cause);
    }
}
