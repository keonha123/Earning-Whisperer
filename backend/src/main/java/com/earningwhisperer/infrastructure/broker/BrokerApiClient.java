package com.earningwhisperer.infrastructure.broker;

/**
 * 증권사 API 추상화 인터페이스.
 * KisApiClient가 구현체. 테스트 시 Mock 교체 가능.
 */
public interface BrokerApiClient {

    /**
     * 주문을 증권사에 제출하고 결과를 반환한다.
     *
     * @throws BrokerApiException 주문 실패 또는 API 오류 시
     */
    BrokerOrderResponse placeOrder(BrokerOrderRequest request);
}
