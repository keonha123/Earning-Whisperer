package com.earningwhisperer.infrastructure.redis;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * AI Engine이 Redis trading-signals 채널에 발행하는 메시지 포맷.
 * api-spec.md Contract 2 규격을 따름.
 *
 * 인입 JSON 키는 `raw_score`(Contract 2 명세)이고 백엔드 내부 필드명은 `aiScore`로 유지한다.
 * 백엔드는 이 값을 룰 엔진/WebSocket 전파 단계에서 일관되게 "AI 점수"로 다루므로
 * outbound DTO(LiveSignalMessage, TradeCommandMessage 등)는 `ai_score`로 직렬화한다.
 */
@Getter
@NoArgsConstructor
public class TradingSignalMessage {

    private String ticker;

    @JsonProperty("raw_score")
    private double aiScore;

    private String rationale;

    @JsonProperty("text_chunk")
    private String textChunk;

    /** AI 분석 완료 시점 (UTC Unix Epoch Second) */
    private long timestamp;
}
