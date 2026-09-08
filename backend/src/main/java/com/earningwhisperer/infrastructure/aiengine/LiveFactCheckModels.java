package com.earningwhisperer.infrastructure.aiengine;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * AI Engine 실시간 팩트체크 계약(Contract 9) 의 요청/응답 모델.
 *
 * <p>AI Engine 은 응답 필드를 추가할 수 있으므로 모든 응답 레코드는
 * {@code @JsonIgnoreProperties(ignoreUnknown = true)} 로 둔다. 백엔드가 모르는 필드가
 * 하나 늘었다고 시연 도중 역직렬화가 깨지면 안 된다.
 */
public final class LiveFactCheckModels {

    private LiveFactCheckModels() {
    }

    /**
     * 문장 1개 제출 요청.
     *
     * @param sentenceTimestamp Unix Epoch Second. AI Engine 이 이 값을 기준으로 과거 N일의
     *                          뉴스 근거를 검색하므로 <b>반드시 실제 현재 시각</b>이어야 한다.
     *                          스크립트에 박힌 과거/미래 시각을 넣으면 근거가 적재되어 있어도
     *                          검색 결과가 0건이 되어 전부 INSUFFICIENT_EVIDENCE 로 떨어진다.
     */
    public record SentenceRequest(
            String ticker,
            String sentence,
            @JsonProperty("sentence_sequence") int sentenceSequence,
            @JsonProperty("sentence_timestamp") long sentenceTimestamp,
            @JsonProperty("is_session_end") boolean isSessionEnd
    ) {
    }

    /** 배치 응답. {@code status} 가 COMPLETED 일 때만 {@code claims} 가 채워진다. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record BatchResponse(
            String ticker,
            String status,
            @JsonProperty("buffered_count") int bufferedCount,
            @JsonProperty("batch_start_sequence") Integer batchStartSequence,
            @JsonProperty("batch_end_sequence") Integer batchEndSequence,
            List<Claim> claims,
            @JsonProperty("excluded_count") int excludedCount,
            @JsonProperty("extraction_llm_used") boolean extractionLlmUsed,
            @JsonProperty("verification_llm_used") boolean verificationLlmUsed,
            List<String> warnings
    ) {
        public boolean isCompleted() {
            return "COMPLETED".equals(status);
        }

        public boolean hasClaims() {
            return claims != null && !claims.isEmpty();
        }
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Claim(
            @JsonProperty("claim_id") String claimId,
            @JsonProperty("sentence_index") int sentenceIndex,
            @JsonProperty("source_text") String sourceText,
            String claim,
            @JsonProperty("claim_type") String claimType,
            String verdict,
            double confidence,
            @JsonProperty("explanation_ko") String explanationKo,
            @JsonProperty("reason_code") String reasonCode,
            List<Evidence> evidence,
            @JsonProperty("retrieved_count") int retrievedCount,
            @JsonProperty("accepted_count") int acceptedCount
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Evidence(
            @JsonProperty("doc_id") String docId,
            String title,
            String snippet,
            String url,
            String source,
            @JsonProperty("published_at") long publishedAt,
            @JsonProperty("relevance_score") double relevanceScore
    ) {
    }
}
