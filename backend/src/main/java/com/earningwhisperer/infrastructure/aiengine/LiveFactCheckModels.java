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
     * @param sentenceTimestamp Original statement time (UTC epoch seconds), including historical
     *                          call time for replay. Never replace historical cutoff with wall-clock now.
     * @param callId Optional call identity to isolate simultaneous/replayed calls for one ticker.
     */
    public record SentenceRequest(
            String ticker,
            String sentence,
            @JsonProperty("sentence_sequence") int sentenceSequence,
            @JsonProperty("sentence_timestamp") long sentenceTimestamp,
            @JsonProperty("is_session_end") boolean isSessionEnd,
            @JsonProperty("call_id") String callId
    ) {
        public SentenceRequest(String ticker, String sentence, int sequence, long timestamp, boolean end) {
            this(ticker, sentence, sequence, timestamp, end, null);
        }
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
