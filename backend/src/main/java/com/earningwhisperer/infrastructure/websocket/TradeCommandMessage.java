package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

/**
 * Contract 3b — 백엔드 → Trading Terminal 매매 명령 메시지.
 *
 * Private WebSocket /user/{userId}/queue/signals 로 전송.
 * Trading Terminal은 이 메시지를 수신하여 KIS API로 실제 주문을 실행한다.
 *
 * orderRatio 의미론:
 * - BUY: 예수금 대비 매수 비율. qty = floor((orderableCash × orderRatio) / currentPrice)
 * - SELL: 보유수량 대비 매도 비율. qty = floor(holdingQty × orderRatio). 0이면 주문 안 함.
 * 수량 산출 책임은 Trading Terminal에 있으며, 서버는 비율까지만 결정한다(자본시장법 준수).
 */
@Getter
@Builder
public class TradeCommandMessage {

    @JsonProperty("trade_id")
    private final Long tradeId;

    /** BUY | SELL */
    private final String action;

    @JsonProperty("order_ratio")
    private final double orderRatio;

    private final String ticker;

    @JsonProperty("ai_score")
    private final double aiScore;
}
