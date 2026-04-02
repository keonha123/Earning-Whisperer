package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

/**
 * Contract 4.1: Backend → Frontend WebSocket 메시지 포맷.
 * Topic: /topic/live/demo (쇼케이스 데모룸 전용)
 *
 * LiveSignalMessage(/topic/live/{ticker})와 달리
 * is_session_end 필드를 포함하여 루프 재시작 시점을 프론트엔드에 알린다.
 */
@Getter
@Builder
public class DemoSignalMessage {

    private String ticker;

    @JsonProperty("text_chunk")
    private String textChunk;

    @JsonProperty("raw_score")
    private double rawScore;

    @JsonProperty("ema_score")
    private double emaScore;

    private String rationale;
    private String action;
    private long timestamp;

    /**
     * 루프 마지막 이벤트 직후 true로 발행.
     * 프론트엔드가 "세션 종료 — 재시작" UI를 표시하는 트리거.
     */
    @JsonProperty("is_session_end")
    private boolean isSessionEnd;
}
