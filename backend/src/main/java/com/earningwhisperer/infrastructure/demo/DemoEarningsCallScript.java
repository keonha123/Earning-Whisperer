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
         * 실제 어닝콜이 열린 시각 (ISO-8601, 예 {@code 2026-08-20T13:00:00Z}).
         *
         * <p>비워 두면 세그먼트 타임스탬프를 재생 시점의 현재 시각으로 찍는다. 그러면
         * AI Engine 이 "지금부터 과거 30일" 을 근거 검색 창으로 잡으므로, <b>과거 어닝콜을
         * 재생할 때는 그 콜 시점의 뉴스가 창 밖으로 밀려나 전부 근거 부족이 된다.</b>
         *
         * <p>값을 채우면 타임스탬프를 {@code call_started_at + start_ms} 로 계산한다.
         * 재생 대상이 과거 이벤트이므로 근거 검색의 기준 시각도 그 이벤트의 시각인 것이
         * 맞다. 검색 창을 억지로 늘리는 것과는 다르다 — 늘리면 무관한 최신 뉴스까지 딸려온다.
         */
        @JsonProperty("call_started_at")
        String callStartedAt,

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
