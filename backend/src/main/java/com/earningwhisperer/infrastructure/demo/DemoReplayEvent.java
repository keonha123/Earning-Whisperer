package com.earningwhisperer.infrastructure.demo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * mock-nvda-replay.json 스크립트 파일의 단일 이벤트 파싱용 레코드.
 *
 * 필드는 모두 사전 계산된 값이며, DemoReplayService가 그대로 브로드캐스트한다.
 * 실제 파이프라인(AI Engine → SignalService → RuleEngine)을 거치지 않는다.
 */
public record DemoReplayEvent(
        String ticker,

        @JsonProperty("text_chunk")
        String textChunk,

        @JsonProperty("raw_score")
        double rawScore,

        @JsonProperty("ema_score")
        double emaScore,

        String rationale,
        String action,
        long timestamp
) {
}
