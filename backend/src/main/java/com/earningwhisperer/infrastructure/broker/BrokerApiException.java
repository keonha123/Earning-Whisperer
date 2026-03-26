package com.earningwhisperer.infrastructure.broker;

/**
 * 증권사 API 호출 실패 시 발생하는 예외.
 * TradeService에서 catch하여 Trade 상태를 FAILED로 전환.
 */
public class BrokerApiException extends RuntimeException {

    public BrokerApiException(String message) {
        super(message);
    }

    public BrokerApiException(String message, Throwable cause) {
        super(message, cause);
    }
}
