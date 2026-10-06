package com.earningwhisperer.infrastructure.aiengine;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 엔진 계약(Contract 9.10) 필드명 검증. 응답 레코드는 모르는 필드를 무시하므로, 필드명이 틀리면
 * 값이 조용히 null 이 되고 번역이 하나도 발행되지 않는다. 실제 JSON 으로 확인한다.
 */
@DisplayName("TranscriptTranslationModels")
class TranscriptTranslationModelsTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    @DisplayName("응답의 snake_case 필드를 읽고 모르는 필드는 무시한다")
    void 응답_역직렬화() throws Exception {
        String json = """
                {"available": true, "sequence": 3, "text_ko": "기존점 매출은 2.6%였습니다.",
                 "terms_used": ["comp sales"], "warnings": [], "model": "gemini-3.1-flash-lite"}
                """;

        TranscriptTranslationModels.TranslateResponse response =
                objectMapper.readValue(json, TranscriptTranslationModels.TranslateResponse.class);

        assertThat(response.hasText()).isTrue();
        assertThat(response.sequence()).isEqualTo(3);
        assertThat(response.textKo()).isEqualTo("기존점 매출은 2.6%였습니다.");
        assertThat(response.termsUsed()).containsExactly("comp sales");
    }

    @Test
    @DisplayName("실패 응답은 hasText 가 false 다")
    void 실패_응답() throws Exception {
        String json = """
                {"available": false, "sequence": 3, "text_ko": null, "terms_used": [], "warnings": ["translation_llm_failed"]}
                """;

        TranscriptTranslationModels.TranslateResponse response =
                objectMapper.readValue(json, TranscriptTranslationModels.TranslateResponse.class);

        assertThat(response.hasText()).isFalse();
        assertThat(response.warnings()).containsExactly("translation_llm_failed");
    }

    @Test
    @DisplayName("요청은 call_id 를 snake_case 로 내보낸다")
    void 요청_직렬화() {
        JsonNode json = objectMapper.valueToTree(new TranscriptTranslationModels.TranslateRequest(
                "WMT", "demo-1", 0, "Comp sales were 2.6%.",
                List.of(new TranscriptTranslationModels.Term("Comp sales", "기존점 매출"))));

        assertThat(json.has("call_id")).isTrue();
        assertThat(json.has("callId")).isFalse();
        assertThat(json.get("terms").get(0).get("term").asText()).isEqualTo("Comp sales");
        assertThat(json.get("terms").get(0).get("ko").asText()).isEqualTo("기존점 매출");
    }
}
