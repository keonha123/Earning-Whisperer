package com.earningwhisperer.infrastructure.aiengine;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import java.io.InputStream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * AI Engine 응답 역직렬화 계약 테스트.
 *
 * <p>fixture 는 <b>실제 AI Engine 이 반환한 응답을 그대로 저장한 것</b>이다 (Gemini 실호출,
 * Oracle 어닝콜 문장 3개 + 뉴스 근거 2건). 손으로 쓴 JSON 으로 검증하면 필드명이 실제와
 * 어긋나도 테스트는 통과한다. 그 함정을 피하려고 실측 응답을 고정해 두었다.
 *
 * <p>AI Engine 이 응답 형식을 바꾸면 이 테스트가 먼저 깨진다.
 */
@DisplayName("AI Engine 팩트체크 응답 역직렬화")
class LiveFactCheckModelsTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private LiveFactCheckModels.BatchResponse load() throws Exception {
        try (InputStream in = new ClassPathResource("aiengine/live-fact-check-completed.json").getInputStream()) {
            return objectMapper.readValue(in, LiveFactCheckModels.BatchResponse.class);
        }
    }

    @Test
    @DisplayName("실제 COMPLETED 응답의 모든 필드가 매핑된다")
    void 실제_응답_역직렬화() throws Exception {
        LiveFactCheckModels.BatchResponse batch = load();

        assertThat(batch.ticker()).isEqualTo("ORCL");
        assertThat(batch.status()).isEqualTo("COMPLETED");
        assertThat(batch.isCompleted()).isTrue();
        assertThat(batch.hasClaims()).isTrue();
        assertThat(batch.batchStartSequence()).isZero();
        assertThat(batch.batchEndSequence()).isEqualTo(2);
        assertThat(batch.extractionLlmUsed()).isTrue();
        assertThat(batch.verificationLlmUsed()).isTrue();
    }

    @Test
    @DisplayName("판정 3종이 모두 계약대로 들어온다")
    void 판정값_계약() throws Exception {
        LiveFactCheckModels.BatchResponse batch = load();

        assertThat(batch.claims()).extracting(LiveFactCheckModels.Claim::verdict)
                .containsExactlyInAnyOrder("INSUFFICIENT_EVIDENCE", "CONTRADICTED", "SUPPORTED");
    }

    @Test
    @DisplayName("클라이언트가 화면에 쓰는 필드가 비어 있지 않다")
    void 화면_필수_필드() throws Exception {
        LiveFactCheckModels.BatchResponse batch = load();

        assertThat(batch.claims()).allSatisfy(claim -> {
            assertThat(claim.claimId()).isNotBlank();
            assertThat(claim.claim()).isNotBlank();
            // UI 카드에 그대로 노출하는 한국어 설명.
            assertThat(claim.explanationKo()).isNotBlank();
            assertThat(claim.reasonCode()).isNotBlank();
            assertThat(claim.confidence()).isBetween(0.0, 1.0);
        });
    }

    @Test
    @DisplayName("CONTRADICTED 판정에는 근거 문서가 인용된다")
    void 반박_판정의_근거() throws Exception {
        LiveFactCheckModels.Claim contradicted = load().claims().stream()
                .filter(c -> "CONTRADICTED".equals(c.verdict()))
                .findFirst()
                .orElseThrow();

        assertThat(contradicted.evidence()).isNotEmpty();
        assertThat(contradicted.evidence()).allSatisfy(e -> {
            assertThat(e.docId()).isNotBlank();
            assertThat(e.snippet()).isNotBlank();
            assertThat(e.source()).isNotBlank();
        });
    }

    @Test
    @DisplayName("모르는 필드가 늘어나도 역직렬화가 깨지지 않는다")
    void 알수없는_필드_무시() throws Exception {
        String json = """
                {"ticker":"ORCL","status":"BUFFERING","buffered_count":1,
                 "claims":[],"future_field_from_ai_engine":{"nested":true}}
                """;

        LiveFactCheckModels.BatchResponse batch =
                objectMapper.readValue(json, LiveFactCheckModels.BatchResponse.class);

        assertThat(batch.status()).isEqualTo("BUFFERING");
        assertThat(batch.isCompleted()).isFalse();
        assertThat(batch.hasClaims()).isFalse();
    }
}
