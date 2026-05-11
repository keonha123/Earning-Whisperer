package com.earningwhisperer.domain.trade;

/**
 * 콜백 멱등성 가드용 도메인 예외.
 *
 * 이미 종결 상태(EXECUTED/FAILED)인 Trade에 대해 다른 결과로 콜백이 들어왔거나,
 * EXECUTED → FAILED 같은 비정상 전이를 시도했을 때 throw 한다.
 * GlobalExceptionHandler 가 409 Conflict 로 매핑한다.
 */
public class TradeStateConflictException extends RuntimeException {

    public TradeStateConflictException(String message) {
        super(message);
    }
}
