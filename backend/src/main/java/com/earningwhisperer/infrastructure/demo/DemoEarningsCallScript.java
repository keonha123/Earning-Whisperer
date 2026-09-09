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

        /**
         * 연쇄 영향을 볼 종목. AI Engine 의 정적 관계 그래프는 일부 종목만 담고 있어서,
         * 시연 종목이 거기 없으면 파급효과가 빈 배열로 나온다. 여기에 적어 두면 엔진이
         * 그 종목들을 영향 후보로 잡는다.
         */
        @JsonProperty("related_tickers")
        List<String> relatedTickers,

        /** 회피 탐지에 쓸 애널리스트 Q&A. 없으면 종합 화면의 회피 지표가 생략된다. */
        @JsonProperty("analyst_qa")
        AnalystQa analystQa,

        List<Segment> segments
) {

    /**
     * 회피 탐지 입력.
     *
     * <p>어닝콜 Q&A 세션에서 실제로 오간 질문 하나와 그 답변을 그대로 옮겨 적는다.
     * 엔진은 질문에 등장한 주제가 답변에서 다뤄졌는지를 보고 회피 점수를 낸다.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record AnalystQa(
            String question,
            String answer
    ) {
    }

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
