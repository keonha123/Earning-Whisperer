package com.earningwhisperer.infrastructure.broker;

import com.earningwhisperer.domain.signal.TradeAction;

/**
 * 증권사 주문 요청 값 객체.
 * BUY 또는 SELL만 허용 (HOLD는 TradeService에서 사전 필터링).
 */
public record BrokerOrderRequest(String ticker, TradeAction side, int orderQty) {}
