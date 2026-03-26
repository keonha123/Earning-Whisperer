package com.earningwhisperer.infrastructure.broker;

/**
 * 증권사 주문 응답 값 객체.
 * brokerOrderId: 증권사가 부여한 주문 번호 (취소/조회 시 사용).
 * executedQty: 체결된 수량 (모의투자에서는 즉시 체결 가정으로 orderQty와 동일).
 */
public record BrokerOrderResponse(String brokerOrderId, int executedQty) {}
