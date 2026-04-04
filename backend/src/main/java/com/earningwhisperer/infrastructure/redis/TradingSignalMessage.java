package com.earningwhisperer.infrastructure.redis;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * AI Engine이 Redis trading-signals 채널에 발행하는 메시지 포맷.
 * api-spec.md Contract 2 규격을 따름.
 */
@Getter
@NoArgsConstructor
public class TradingSignalMessage {

    private String ticker;

    @JsonProperty("raw_score")
    private double rawScore;

    private String rationale;

    @JsonProperty("text_chunk")
    private String textChunk;

    /** AI 분석 완료 시점 (UTC Unix Epoch Second) */
    private long timestamp;
}
