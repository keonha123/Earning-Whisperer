package com.earningwhisperer.infrastructure.aiengine;

import com.earningwhisperer.infrastructure.websocket.EarningsSummaryPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 역직렬화/직렬화 계약 테스트.
 *
 * <p>이 프로젝트는 전역 네이밍 전략을 쓰지 않아 {@code @JsonProperty} 이름을 전부 손으로
 * 적었다. 오타가 나면 {@code ignoreUnknown=true} 때문에 <b>예외 없이 그 필드만 null</b> 이
 * 되고, {@code NON_NULL} 직렬화를 거치며 페이로드에서 통째로 사라진다. 화면에서는
 * "엔진이 안 준 것" 과 구분되지 않는다. 그래서 record 를 자바로 만들어 검사하는 테스트로는
 * 절대 잡히지 않고, 반드시 실제 JSON 을 통과시켜야 한다.
 */
class EarningsSummaryModelsTest {

    private final ObjectMapper mapper = new ObjectMapper();

    /** AI Engine 실응답에서 화면이 쓰는 필드만 추린 것 (Contract 9.6). */
    private static final String ANALYZE_JSON = """
            {
              "analysis": {
                "direction": "BULLISH",
                "magnitude": 0.85,
                "confidence": 0.74,
                "catalyst_type": "EARNINGS_GUIDANCE_UPGRADE",
                "rationale": "Oracle's cloud momentum is accelerating.",
                "risk_flags": ["missing_rag_evidence", "thin_confirmation"],
                "hold_days": 1,
                "model_version": "gemini-3.6-flash",
                "review_triggered": false,
                "cot_reasoning": "무시되어야 하는 미지의 필드"
              },
              "signal_brief": {
                "action": "AVOID",
                "gate_result": "soft_block",
                "decision_state": "tradable",
                "institutional_grade": "D",
                "institutional_grade_score": 48.06,
                "institutional_approval_state": "research_only",
                "position_intent_ko": "신규 진입 금지",
                "no_trade_summary_ko": "Hard risk blocker 감지",
                "risk_flags_ko": ["거래량 확인이 약합니다."],
                "counter_thesis_ko": "반대 논거",
                "recommended_hold_days": 1
              }
            }""";

    /** Contract 9.7 실응답에서 화면이 쓰는 필드만 추린 것. */
    private static final String INTELLIGENCE_JSON = """
            {
              "omission_evasion": {
                "evasion_score": 0.5571,
                "directness": 0.4429,
                "omission_score": 1.0,
                "pivot_detected": true,
                "missing_topics": ["capex", "margin"],
                "rationale_ko": "핵심 주제를 누락했습니다."
              },
              "impact_chain": [
                {
                  "ticker": "NVDA",
                  "relationship": "supplier",
                  "direction": "positive",
                  "impact_score": 0.56,
                  "confidence": 0.45,
                  "rationale_ko": "연쇄 영향 근거"
                }
              ],
              "risk_plan": {
                "available": true,
                "direction": "LONG",
                "reference_price": 242.5,
                "stop_loss": 232.4775,
                "take_profit_1": 255.0282,
                "take_profit_2": 262.5451,
                "stop_pct": 4.133,
                "take_profit_1_pct": 5.166,
                "take_profit_2_pct": 8.266,
                "risk_reward_1": 1.25,
                "time_stop_days": 3,
                "invalidation_text": "손절 이탈 시 무효",
                "sizing_note_ko": "분할 진입"
              },
              "summary_ko": "무시되어야 하는 미지의 필드",
              "warnings": ["RAG evidence is empty"]
            }""";

    @Test
    void analyze_응답의_모든_필드가_바인딩된다() throws Exception {
        EarningsSummaryModels.AnalyzeResponse response =
                mapper.readValue(ANALYZE_JSON, EarningsSummaryModels.AnalyzeResponse.class);

        assertThat(response.hasAnalysis()).isTrue();
        EarningsSummaryModels.Analysis a = response.analysis();
        assertThat(a.direction()).isEqualTo("BULLISH");
        assertThat(a.magnitude()).isEqualTo(0.85);
        assertThat(a.confidence()).isEqualTo(0.74);
        assertThat(a.catalystType()).isEqualTo("EARNINGS_GUIDANCE_UPGRADE");
        assertThat(a.rationale()).isNotBlank();
        assertThat(a.riskFlags()).containsExactly("missing_rag_evidence", "thin_confirmation");
        assertThat(a.holdDays()).isEqualTo(1);
        assertThat(a.modelVersion()).isEqualTo("gemini-3.6-flash");
        assertThat(a.reviewTriggered()).isFalse();

        EarningsSummaryModels.SignalBrief g = response.signalBrief();
        assertThat(g.action()).isEqualTo("AVOID");
        assertThat(g.gateResult()).isEqualTo("soft_block");
        assertThat(g.decisionState()).isEqualTo("tradable");
        assertThat(g.institutionalGrade()).isEqualTo("D");
        assertThat(g.institutionalGradeScore()).isEqualTo(48.06);
        assertThat(g.institutionalApprovalState()).isEqualTo("research_only");
        assertThat(g.positionIntentKo()).isNotBlank();
        assertThat(g.noTradeSummaryKo()).isNotBlank();
        assertThat(g.riskFlagsKo()).hasSize(1);
        assertThat(g.counterThesisKo()).isNotBlank();
        assertThat(g.recommendedHoldDays()).isEqualTo(1);
    }

    @Test
    void intelligence_응답의_모든_필드가_바인딩된다() throws Exception {
        EarningsSummaryModels.IntelligenceResponse response =
                mapper.readValue(INTELLIGENCE_JSON, EarningsSummaryModels.IntelligenceResponse.class);

        EarningsSummaryModels.OmissionEvasion e = response.omissionEvasion();
        assertThat(e.evasionScore()).isEqualTo(0.5571);
        assertThat(e.directness()).isEqualTo(0.4429);
        assertThat(e.omissionScore()).isEqualTo(1.0);
        assertThat(e.pivotDetected()).isTrue();
        assertThat(e.missingTopics()).containsExactly("capex", "margin");
        assertThat(e.rationaleKo()).isNotBlank();

        EarningsSummaryModels.ImpactLink link = response.impactChain().get(0);
        assertThat(link.ticker()).isEqualTo("NVDA");
        assertThat(link.relationship()).isEqualTo("supplier");
        assertThat(link.direction()).isEqualTo("positive");
        assertThat(link.impactScore()).isEqualTo(0.56);
        assertThat(link.confidence()).isEqualTo(0.45);
        assertThat(link.rationaleKo()).isNotBlank();

        EarningsSummaryModels.RiskPlan p = response.riskPlan();
        assertThat(p.available()).isTrue();
        assertThat(p.direction()).isEqualTo("LONG");
        assertThat(p.referencePrice()).isEqualTo(242.5);
        assertThat(p.stopLoss()).isEqualTo(232.4775);
        assertThat(p.takeProfit1()).isEqualTo(255.0282);
        assertThat(p.takeProfit2()).isEqualTo(262.5451);
        assertThat(p.stopPct()).isEqualTo(4.133);
        assertThat(p.takeProfit1Pct()).isEqualTo(5.166);
        assertThat(p.takeProfit2Pct()).isEqualTo(8.266);
        assertThat(p.riskReward1()).isEqualTo(1.25);
        assertThat(p.timeStopDays()).isEqualTo(3);
        assertThat(p.invalidationText()).isNotBlank();
        assertThat(p.sizingNoteKo()).isNotBlank();

        assertThat(response.warnings()).containsExactly("RAG evidence is empty");
    }

    @Test
    void 엔진이_available_키를_빼면_null_이_된다() throws Exception {
        // false 로 둔갑하면 "엔진이 계획 없다고 답했다" 로 읽힌다. null 이어야 호출자가 경고한다.
        EarningsSummaryModels.RiskPlan plan = mapper.readValue(
                "{\"direction\":\"LONG\"}", EarningsSummaryModels.RiskPlan.class);
        assertThat(plan.available()).isNull();
    }

    @Test
    void STOMP_페이로드는_계약대로_snake_case_로_나간다() throws Exception {
        EarningsSummaryPublisher.Payload payload = EarningsSummaryPublisher.Payload.builder()
                .ticker("ORCL")
                .callId("demo-orcl-1")
                .generatedAt("2026-09-09T09:47:50Z")
                .judgment(mapper.readValue(ANALYZE_JSON, EarningsSummaryModels.AnalyzeResponse.class).analysis())
                .intelligenceAvailable(true)
                .impactChain(List.of())
                .warnings(List.of("RAG evidence is empty"))
                .build();

        JsonNode node = mapper.readTree(mapper.writeValueAsString(payload));

        assertThat(node.has("call_id")).isTrue();
        assertThat(node.has("generated_at")).isTrue();
        assertThat(node.has("impact_chain")).isTrue();
        assertThat(node.has("intelligence_available")).isTrue();
        assertThat(node.get("judgment").has("catalyst_type")).isTrue();
        assertThat(node.get("judgment").has("risk_flags")).isTrue();
        assertThat(node.get("judgment").has("model_version")).isTrue();
        // NON_NULL 이므로 채우지 않은 필드는 키 자체가 없어야 한다.
        assertThat(node.has("risk_plan")).isFalse();
        assertThat(node.has("evasion")).isFalse();
    }
}
