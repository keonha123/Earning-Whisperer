package com.earningwhisperer.infrastructure.aiengine;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * 어닝콜 종료 후 종합 분석에 쓰는 AI Engine 요청/응답 모델 (Contract 9.6 / 9.7).
 *
 * <p>종합 분석은 엔드포인트 두 개를 합쳐서 만든다. 하나로 끝나지 않는 이유가 있다.
 * <ul>
 *   <li>{@code /v1/engine/analyze} — LLM 이 실제로 판단하는 곳. 방향·강도·신뢰도·촉매
 *       유형·근거 문장과, 그 판단을 실행 가능한지 따지는 기관 등급/게이트가 여기서 나온다.</li>
 *   <li>{@code /v1/engine/earnings/intelligence} — LLM 을 쓰지 않는 규칙 기반 산출물.
 *       질문 회피 정도, 연쇄 영향 후보, 손절/익절 계획이 여기서 나온다.</li>
 * </ul>
 *
 * <p>두 응답 모두 필드가 화면에서 쓰는 것보다 훨씬 많다. 여기서는 화면이 실제로
 * 그리는 것만 선언하고 나머지는 {@code ignoreUnknown} 으로 흘려보낸다. 엔진이 필드를
 * 늘려도 역직렬화가 깨지지 않는다.
 */
public final class EarningsSummaryModels {

    private EarningsSummaryModels() {
    }

    // ── 요청 ────────────────────────────────────────────────────────────────

    /**
     * {@code POST /v1/engine/analyze} 요청.
     *
     * @param prompt      어닝콜 전문(모든 세그먼트를 이어붙인 것)
     * @param needsReview 리뷰 모델까지 태울지. 종합 판단은 회차당 한 번뿐이므로 항상 true.
     * @param marketData  가격 정보. 없으면 null — 엔진은 가격 없이도 판단은 한다.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AnalyzeRequest(
            String ticker,
            String prompt,
            @JsonProperty("needs_review") boolean needsReview,
            @JsonProperty("market_data") Map<String, Object> marketData
    ) {
    }

    /**
     * {@code POST /v1/engine/earnings/intelligence} 요청.
     *
     * @param question       회피 탐지에 쓸 애널리스트 질문. null 이면 회피 점수는 무의미해진다.
     * @param answer         그 질문에 대한 경영진 답변.
     * @param relatedTickers 연쇄 영향을 볼 종목. 엔진의 정적 관계 그래프에 없는 종목도
     *                       여기 실어 보내면 영향 후보로 잡힌다.
     * @param directionHint  analyze 가 낸 방향. 손절/익절 계획의 LONG/SHORT 를 가른다.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record IntelligenceRequest(
            String ticker,
            @JsonProperty("event_text") String eventText,
            String question,
            String answer,
            @JsonProperty("related_tickers") List<String> relatedTickers,
            @JsonProperty("market_data") Map<String, Object> marketData,
            @JsonProperty("direction_hint") String directionHint,
            @JsonProperty("confidence_hint") Double confidenceHint
    ) {
    }

    // ── analyze 응답 ────────────────────────────────────────────────────────

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record AnalyzeResponse(
            Analysis analysis,
            @JsonProperty("signal_brief") SignalBrief signalBrief
    ) {
        /** 판단 본문이 없으면 화면에 그릴 것이 없다. */
        public boolean hasAnalysis() {
            return analysis != null && analysis.direction() != null;
        }
    }

    /** LLM 판단 본문. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Analysis(
            /** BULLISH / BEARISH / NEUTRAL */
            String direction,
            /** 0~1. 방향의 강도. */
            Double magnitude,
            /** 0~1. */
            Double confidence,
            @JsonProperty("catalyst_type") String catalystType,
            /** LLM 이 쓴 판단 근거(영문). */
            String rationale,
            @JsonProperty("risk_flags") List<String> riskFlags,
            @JsonProperty("hold_days") Integer holdDays,
            @JsonProperty("model_version") String modelVersion,
            @JsonProperty("review_triggered") Boolean reviewTriggered
    ) {
    }

    /**
     * 판단을 실행에 옮겨도 되는지 따진 결과.
     *
     * <p>주의: {@code action} 은 판단 방향이 아니라 <b>게이트 통과 여부</b>다. 근거가
     * 부족하면 BULLISH 판단에도 AVOID 가 나온다. 화면에서 둘을 같은 줄에 놓으면
     * 모순으로 읽히므로 반드시 분리해 표시한다.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SignalBrief(
            String action,
            @JsonProperty("gate_result") String gateResult,
            @JsonProperty("decision_state") String decisionState,
            /** A~E. */
            @JsonProperty("institutional_grade") String institutionalGrade,
            @JsonProperty("institutional_grade_score") Double institutionalGradeScore,
            @JsonProperty("institutional_approval_state") String institutionalApprovalState,
            @JsonProperty("position_intent_ko") String positionIntentKo,
            @JsonProperty("no_trade_summary_ko") String noTradeSummaryKo,
            @JsonProperty("risk_flags_ko") List<String> riskFlagsKo,
            @JsonProperty("counter_thesis_ko") String counterThesisKo,
            @JsonProperty("recommended_hold_days") Integer recommendedHoldDays
    ) {
    }

    // ── intelligence 응답 ───────────────────────────────────────────────────

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record IntelligenceResponse(
            @JsonProperty("omission_evasion") OmissionEvasion omissionEvasion,
            @JsonProperty("impact_chain") List<ImpactLink> impactChain,
            @JsonProperty("risk_plan") RiskPlan riskPlan,
            List<String> warnings
    ) {
    }

    /**
     * 질문 회피 정도.
     *
     * @param evasionScore   0~1. 높을수록 질문을 피했다.
     * @param directness     0~1. 높을수록 질문에 정면으로 답했다.
     * @param missingTopics  질문에는 있었으나 답변에 없던 주제.
     * @param pivotDetected  답변이 다른 주제로 방향을 튼 정황.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record OmissionEvasion(
            @JsonProperty("evasion_score") Double evasionScore,
            Double directness,
            @JsonProperty("omission_score") Double omissionScore,
            @JsonProperty("pivot_detected") Boolean pivotDetected,
            @JsonProperty("missing_topics") List<String> missingTopics,
            @JsonProperty("rationale_ko") String rationaleKo
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ImpactLink(
            String ticker,
            String relationship,
            String direction,
            @JsonProperty("impact_score") Double impactScore,
            Double confidence,
            @JsonProperty("rationale_ko") String rationaleKo
    ) {
    }

    /**
     * 손절/익절 계획.
     *
     * <p>{@code available} 이 참이 아니면 나머지 필드는 전부 null 이다. 가격 정보가 없거나
     * 방향성이 서지 않았다는 뜻이므로, 화면은 값을 0 으로 채우지 말고 사유를 보여준다.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RiskPlan(
            /** 엔진이 이 키를 빼면 null 이 된다. 조용히 false 로 두지 않고 호출자가 경고한다. */
            Boolean available,
            String direction,
            @JsonProperty("reference_price") Double referencePrice,
            @JsonProperty("stop_loss") Double stopLoss,
            @JsonProperty("take_profit_1") Double takeProfit1,
            @JsonProperty("take_profit_2") Double takeProfit2,
            @JsonProperty("stop_pct") Double stopPct,
            @JsonProperty("take_profit_1_pct") Double takeProfit1Pct,
            @JsonProperty("take_profit_2_pct") Double takeProfit2Pct,
            @JsonProperty("risk_reward_1") Double riskReward1,
            @JsonProperty("time_stop_days") Integer timeStopDays,
            @JsonProperty("invalidation_text") String invalidationText,
            @JsonProperty("sizing_note_ko") String sizingNoteKo
    ) {
    }
}
