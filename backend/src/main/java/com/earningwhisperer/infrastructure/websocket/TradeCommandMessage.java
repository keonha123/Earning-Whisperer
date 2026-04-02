package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

/**
 * Contract 3b — 백엔드 → Trading Terminal 매매 명령 메시지.
 *
 * Private WebSocket /user/{userId}/queue/signals 로 전송.
 * Trading Terminal은 이 메시지를 수신하여 KIS API로 실제 주문을 실행한다.
 */
@Getter
@Builder
public class TradeCommandMessage {

    @JsonProperty("trade_id")
    private final Long tradeId;

    /** BUY | SELL */
    private final String action;

    @JsonProperty("target_qty")
    private final int targetQty;

    private final String ticker;

    @JsonProperty("ema_score")
    private final double emaScore;
}
