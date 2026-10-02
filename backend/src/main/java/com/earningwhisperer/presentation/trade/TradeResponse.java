package com.earningwhisperer.presentation.trade;

import com.earningwhisperer.domain.trade.OrderType;
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
    private final OrderType orderType;
    private final Integer orderQty;
    /** 주문 지정가. 체결가(executedPrice) 와 달리 미체결 주문에도 존재한다. */
    private final Double price;
    private final Integer executedQty;
    private final Double executedPrice;
    private final TradeStatus status;
    private final String brokerOrderId;
    private final LocalDateTime createdAt;

    public TradeResponse(Trade trade) {
        this.id = trade.getId();
        this.ticker = trade.getTicker();
        this.side = trade.getSide();
        this.orderType = trade.getOrderType();
        this.orderQty = trade.getOrderQty();
        this.price = trade.getPrice();
        this.executedQty = trade.getExecutedQty();
        this.executedPrice = trade.getExecutedPrice();
        this.status = trade.getStatus();
        this.brokerOrderId = trade.getBrokerOrderId();
        this.createdAt = trade.getCreatedAt();
    }
}
