package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

/**
 * Contract 3: Backend → Frontend WebSocket STOMP 메시지 포맷.
 * Topic: /topic/live/{ticker}
 *
 * 프론트엔드에서 수신하는 snake_case JSON으로 직렬화된다.
 */
@Getter
@Builder
public class LiveSignalMessage {

    private String ticker;

    @JsonProperty("text_chunk")
    private String textChunk;

    @JsonProperty("raw_score")
    private double rawScore;

    @JsonProperty("ema_score")
    private double emaScore;

    private String rationale;

    /** 백엔드 룰 엔진의 최종 결정. Phase 4 전까지 항상 HOLD. */
    private String action;

    /** 체결 수량. action이 HOLD이면 0. */
    @JsonProperty("executed_qty")
    private int executedQty;
}
