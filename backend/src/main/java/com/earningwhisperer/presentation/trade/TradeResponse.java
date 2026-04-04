package com.earningwhisperer.presentation.trade;

import com.earningwhisperer.domain.trade.Trade;
import com.earningwhisperer.domain.trade.TradeStatus;
import com.earningwhisperer.domain.signal.TradeAction;
import lombok.Getter;

import java.time.LocalDateTime;

/**
 * 거래 내역 응답 DTO (마이페이지 거래내역 탭용).
 */
@Getter
public class TradeResponse {

    private final Long id;
    private final String ticker;
    private final TradeAction side;
    private final Integer orderQty;
    private final Integer executedQty;
    private final Double price;
    private final TradeStatus status;
    private final String brokerOrderId;
    private final LocalDateTime createdAt;

    public TradeResponse(Trade trade) {
        this.id = trade.getId();
        this.ticker = trade.getTicker();
        this.side = trade.getSide();
        this.orderQty = trade.getOrderQty();
        this.executedQty = trade.getExecutedQty();
        this.price = trade.getPrice();
        this.status = trade.getStatus();
        this.brokerOrderId = trade.getBrokerOrderId();
        this.createdAt = trade.getCreatedAt();
    }
}
