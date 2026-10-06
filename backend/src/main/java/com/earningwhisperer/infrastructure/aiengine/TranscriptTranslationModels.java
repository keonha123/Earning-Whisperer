package com.earningwhisperer.infrastructure.aiengine;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * AI Engine 세그먼트 번역({@code POST /v1/engine/transcript/translate}, Contract 9.10) 요청/응답 모델.
 *
 * <p>{@link TranscriptDiffModels} 와 같은 정책 — 응답 레코드는 모르는 필드를 무시한다.
 */
public final class TranscriptTranslationModels {

    private TranscriptTranslationModels() {
    }

    /**
     * 번역 요청.
     *
     * @param sequence 번역할 묶음의 첫 세그먼트 시퀀스. 엔진은 그대로 돌려줄 뿐 해석하지 않는다.
     * @param text     원문. 묶음이면 세그먼트 원문을 공백으로 이어 붙인 것.
     * @param terms    원문에서 찾은 용어만. 비면 일반 번역.
     */
    public record TranslateRequest(
            String ticker,
            @JsonProperty("call_id") String callId,
            int sequence,
            String text,
            List<Term> terms
    ) {
    }

    /** 번역어를 고정할 용어. {@code term} 은 원문에 나온 표기 그대로다. */
    public record Term(String term, String ko) {
    }

    /**
     * 번역 응답. 실패도 HTTP 200 으로 오며 {@code available=false} 와 {@code warnings} 로 알린다.
     * 실패 시 {@code textKo} 는 null 이다.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record TranslateResponse(
            boolean available,
            int sequence,
            @JsonProperty("text_ko") String textKo,
            @JsonProperty("terms_used") List<String> termsUsed,
            List<String> warnings
    ) {
        /** 화면에 보여줄 번역문이 실제로 있는지. */
        public boolean hasText() {
            return available && textKo != null && !textKo.isBlank();
        }
    }
}
