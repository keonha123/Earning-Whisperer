package com.earningwhisperer.infrastructure.aiengine;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * AI Engine 과거 콜 발언 대조({@code POST /v1/engine/transcript/diff}) 요청/응답 모델.
 *
 * <p>현재 콜의 발언 한 토막을 넘기면 직전 콜에서 같은 주제를 다룬 대목을 찾아
 * 무엇이 달라졌는지 돌려준다. 뉴스 근거 팩트체크와 달리 <b>같은 회사의 과거 발언</b>이
 * 대조 대상이다.
 *
 * <p>{@link LiveFactCheckModels} 와 같은 정책 — 응답 레코드는 모르는 필드를 무시한다.
 */
public final class TranscriptDiffModels {

    private TranscriptDiffModels() {
    }

    /**
     * 대조 요청.
     *
     * @param currentChunk    대조할 현재 발언. 주제어가 없거나 너무 짧으면 엔진이
     *                        {@code current_chunk_not_material} 로 돌려준다.
     * @param sourceType      {@code EARNINGS_CALL} 이 아니면 엔진이 대조하지 않는다.
     * @param requestMetadata {@code timestamp} 에 현재 발언 시각(Epoch Second)을 넣는다.
     *                        엔진은 그 시각 <b>이전</b>의 가장 최근 트랜스크립트를 직전 콜로
     *                        고른다. 비워 두면 적재된 것 중 가장 최근 것을 쓴다.
     */
    public record DiffRequest(
            String ticker,
            @JsonProperty("current_chunk") String currentChunk,
            @JsonProperty("source_type") String sourceType,
            @JsonProperty("request_metadata") java.util.Map<String, Object> requestMetadata
    ) {
        public static DiffRequest forEarningsCall(String ticker, String currentChunk, long timestampEpochSecond) {
            return new DiffRequest(ticker, currentChunk, "EARNINGS_CALL",
                    java.util.Map.of("timestamp", timestampEpochSecond));
        }
    }

    /**
     * 대조 응답.
     *
     * <p>{@code available} 과 {@code items} 는 별개다. 직전 콜을 찾았어도(available=true)
     * 해당 발언이 주제와 무관하거나 근거가 약하면 {@code items} 가 비고 사유가
     * {@code warnings} 에 담긴다. 화면은 이 둘을 구분해서 보여줘야 한다.
     *
     * <p>주요 사유 — {@code previous_transcript_not_found}(직전 콜 미적재),
     * {@code current_chunk_not_material}(주제 무관),
     * {@code weak_prior_transcript_evidence}(검색 근거 부족).
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record DiffResponse(
            boolean available,
            String ticker,
            @JsonProperty("previous_document") PreviousDocument previousDocument,
            List<DiffItem> items,
            List<String> warnings
    ) {
        /** 화면에 보여줄 대조 결과가 실제로 있는지. */
        public boolean hasItems() {
            return available && items != null && !items.isEmpty();
        }
    }

    /** 대조 대상이 된 직전 콜. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record PreviousDocument(
            @JsonProperty("document_id") String documentId,
            String title,
            @JsonProperty("published_at") String publishedAt,
            @JsonProperty("fiscal_quarter") String fiscalQuarter,
            @JsonProperty("source_url") String sourceUrl
    ) {
    }

    /**
     * 대조 항목 1건.
     *
     * @param changeType {@code improved / weakened / unchanged / mixed / new_claim}
     * @param priorClaim 직전 콜의 대응 발언. 없으면 빈 문자열이다.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record DiffItem(
            String topic,
            @JsonProperty("change_type") String changeType,
            @JsonProperty("summary_ko") String summaryKo,
            @JsonProperty("current_claim") String currentClaim,
            @JsonProperty("prior_claim") String priorClaim,
            double confidence,
            @JsonProperty("risk_score") double riskScore,
            List<Evidence> evidence
    ) {
    }

    /** 대조 근거로 쓰인 직전 콜의 발언 토막. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Evidence(
            @JsonProperty("document_id") String documentId,
            String source,
            String title,
            @JsonProperty("published_at") String publishedAt,
            @JsonProperty("source_url") String sourceUrl,
            String snippet,
            @JsonProperty("relevance_score") Double relevanceScore,
            @JsonProperty("confidence_score") Double confidenceScore
    ) {
    }
}
