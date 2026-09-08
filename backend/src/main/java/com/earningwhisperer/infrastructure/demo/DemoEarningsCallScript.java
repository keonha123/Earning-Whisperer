package com.earningwhisperer.infrastructure.demo;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * 시연용 어닝콜 스크립트 파일(JSON) 파싱 모델.
 *
 * <p>실제 서비스에서는 Data Pipeline 이 STT 로 만들어 보내는 세그먼트를, 시연에서는 이
 * 파일이 대신한다. 인입 이후 경로(검증 → STOMP fan-out → 팩트체크)는 실제와 동일하다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record DemoEarningsCallScript(
        String ticker,

        @JsonProperty("company_name")
        String companyName,

        @JsonProperty("session_label")
        String sessionLabel,

        /** callId 접두사. 실제 callId 는 재생 시작 시각을 붙여 매 회차 새로 만든다. */
        @JsonProperty("call_id_prefix")
        String callIdPrefix,

        List<Segment> segments
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Segment(
            int sequence,

            @JsonProperty("start_ms")
            long startMs,

            @JsonProperty("end_ms")
            long endMs,

            String speaker,

            String text
    ) {
    }
}
