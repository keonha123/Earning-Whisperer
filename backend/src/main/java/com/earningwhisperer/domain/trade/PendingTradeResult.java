package com.earningwhisperer.domain.trade;

/**
 * createPendingTrade() 반환값.
 * TradingSignalSubscriber가 tradeId와 userId를 함께 받아 Private WebSocket 라우팅에 사용한다.
 */
public record PendingTradeResult(Long tradeId, Long userId) {}
