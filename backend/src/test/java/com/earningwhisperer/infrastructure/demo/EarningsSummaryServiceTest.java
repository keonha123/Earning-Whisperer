package com.earningwhisperer.infrastructure.demo;

import com.earningwhisperer.domain.stock.StockPriceSnapshot;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.aiengine.EarningsSummaryModels;
import com.earningwhisperer.infrastructure.websocket.EarningsSummaryPublisher;
import com.earningwhisperer.infrastructure.websocket.StockPriceCache;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 어닝콜 종료 후 종합 판단 파이프 테스트.
 *
 * <p>검증 대상은 "엔진이 무엇을 돌려주든 화면에 잘못된 것을 그리지 않는가" 다.
 * 판단이 없으면 발행하지 않고, 부가 정보만 없으면 판단은 살린다.
 */
class EarningsSummaryServiceTest {

    private static final DemoEarningsCallScript SCRIPT = new DemoEarningsCallScript(
            "ORCL", "Oracle", "Q4", "demo",
            List.of("NVDA", "MSFT"),
            new DemoEarningsCallScript.AnalystQa("capex 전망은?", "수요 환경이 매우 좋습니다."),
            List.of(
                    new DemoEarningsCallScript.Segment(0, 0, 1000, "CEO", "OCI 매출이 52% 늘었습니다."),
                    new DemoEarningsCallScript.Segment(1, 1000, 2000, "CEO", "RPO 는 1380억 달러입니다.")
            ));

    @Test
    void 판단과_부가정보를_한_페이로드로_묶어_발행한다() {
        AtomicReference<EarningsSummaryPublisher.Payload> published = new AtomicReference<>();
        EarningsSummaryService service = new EarningsSummaryService(
                clientOf(Optional.of(analyzeResponse("BULLISH", 0.74)), Optional.of(intelligenceResponse())),
                capturingPublisher(published),
                priceCache(Map.of("ORCL", new StockPriceSnapshot("ORCL", 242.5, 236.1, 2.7, 0L))));

        boolean result = service.summarizeAndPublish("ORCL", "call-1", SCRIPT);

        assertThat(result).isTrue();
        EarningsSummaryPublisher.Payload payload = published.get();
        assertThat(payload.getTicker()).isEqualTo("ORCL");
        assertThat(payload.getCallId()).isEqualTo("call-1");
        assertThat(payload.getJudgment().direction()).isEqualTo("BULLISH");
        assertThat(payload.getGate().action()).isEqualTo("AVOID");
        assertThat(payload.getEvasion().evasionScore()).isEqualTo(0.56);
        assertThat(payload.getImpactChain()).extracting(EarningsSummaryModels.ImpactLink::ticker)
                .containsExactly("NVDA");
        assertThat(payload.getRiskPlan().available()).isTrue();
        assertThat(payload.getWarnings()).containsExactly("RAG evidence is empty");
    }

    @Test
    void 판단_본문이_없으면_발행하지_않는다() {
        AtomicReference<EarningsSummaryPublisher.Payload> published = new AtomicReference<>();
        EarningsSummaryService service = new EarningsSummaryService(
                clientOf(Optional.empty(), Optional.of(intelligenceResponse())),
                capturingPublisher(published), priceCache(Map.of()));

        assertThat(service.summarizeAndPublish("ORCL", "call-1", SCRIPT)).isFalse();
        assertThat(published.get()).isNull();
    }

    @Test
    void 부가정보가_없어도_판단은_발행한다() {
        // intelligence 는 규칙 기반이라 잘 죽지 않지만, 죽었다고 LLM 판단까지 버리면
        // 시연에서 화면이 통째로 비어 버린다.
        AtomicReference<EarningsSummaryPublisher.Payload> published = new AtomicReference<>();
        EarningsSummaryService service = new EarningsSummaryService(
                clientOf(Optional.of(analyzeResponse("BEARISH", 0.4)), Optional.empty()),
                capturingPublisher(published), priceCache(Map.of()));

        assertThat(service.summarizeAndPublish("ORCL", "call-1", SCRIPT)).isTrue();
        assertThat(published.get().getJudgment().direction()).isEqualTo("BEARISH");
        assertThat(published.get().getEvasion()).isNull();
        assertThat(published.get().getRiskPlan()).isNull();
    }

    @Test
    void 종합_판단이_비활성화되면_엔진을_부르지_않는다() {
        List<String> calls = new ArrayList<>();
        AiEngineClient disabled = new AiEngineClient(null, false, false) {
            @Override
            public Optional<EarningsSummaryModels.AnalyzeResponse> analyze(
                    EarningsSummaryModels.AnalyzeRequest request) {
                calls.add("analyze");
                return Optional.empty();
            }
        };
        EarningsSummaryService service = new EarningsSummaryService(
                disabled, capturingPublisher(new AtomicReference<>()), priceCache(Map.of()));

        assertThat(service.summarizeAndPublish("ORCL", "call-1", SCRIPT)).isFalse();
        assertThat(calls).isEmpty();
    }

    @Test
    void 가격_정보가_없으면_market_data_를_지어내지_않는다() {
        AtomicReference<EarningsSummaryModels.AnalyzeRequest> sent = new AtomicReference<>();
        AiEngineClient client = new AiEngineClient(null, true, true) {
            @Override
            public Optional<EarningsSummaryModels.AnalyzeResponse> analyze(
                    EarningsSummaryModels.AnalyzeRequest request) {
                sent.set(request);
                return Optional.of(analyzeResponse("NEUTRAL", 0.2));
            }

            @Override
            public Optional<EarningsSummaryModels.IntelligenceResponse> earningsIntelligence(
                    EarningsSummaryModels.IntelligenceRequest request) {
                return Optional.empty();
            }
        };
        EarningsSummaryService service = new EarningsSummaryService(
                client, capturingPublisher(new AtomicReference<>()), priceCache(Map.of()));

        service.summarizeAndPublish("ORCL", "call-1", SCRIPT);

        assertThat(sent.get().marketData()).isNull();
    }

    @Test
    void 관련종목과_QA_가_인텔리전스_요청에_실린다() {
        // AI Engine 의 정적 관계 그래프에 없는 종목은 여기로 넘기지 않으면 파급효과가
        // 빈 배열로 나온다. 회피 점수도 질문 없이는 의미가 없다.
        AtomicReference<EarningsSummaryModels.IntelligenceRequest> sent = new AtomicReference<>();
        AiEngineClient client = new AiEngineClient(null, true, true) {
            @Override
            public Optional<EarningsSummaryModels.AnalyzeResponse> analyze(
                    EarningsSummaryModels.AnalyzeRequest request) {
                return Optional.of(analyzeResponse("BULLISH", 0.74));
            }

            @Override
            public Optional<EarningsSummaryModels.IntelligenceResponse> earningsIntelligence(
                    EarningsSummaryModels.IntelligenceRequest request) {
                sent.set(request);
                return Optional.of(intelligenceResponse());
            }
        };
        EarningsSummaryService service = new EarningsSummaryService(
                client, capturingPublisher(new AtomicReference<>()), priceCache(Map.of()));

        service.summarizeAndPublish("ORCL", "call-1", SCRIPT);

        assertThat(sent.get().relatedTickers()).containsExactly("NVDA", "MSFT");
        assertThat(sent.get().question()).isEqualTo("capex 전망은?");
        assertThat(sent.get().directionHint()).isEqualTo("BULLISH");
        assertThat(sent.get().eventText()).contains("OCI 매출이 52% 늘었습니다.").contains("RPO");
    }

    @Test
    void 전문이_비면_발행하지_않는다() {
        DemoEarningsCallScript empty = new DemoEarningsCallScript(
                "ORCL", "Oracle", "Q4", "demo", null, null, List.of());
        AtomicReference<EarningsSummaryPublisher.Payload> published = new AtomicReference<>();
        EarningsSummaryService service = new EarningsSummaryService(
                clientOf(Optional.of(analyzeResponse("BULLISH", 0.7)), Optional.of(intelligenceResponse())),
                capturingPublisher(published), priceCache(Map.of()));

        assertThat(service.summarizeAndPublish("ORCL", "call-1", empty)).isFalse();
        assertThat(published.get()).isNull();
    }

    @Test
    void 판단_객체는_왔지만_방향이_없으면_발행하지_않는다() {
        // 엔진이 응답은 했는데 판단을 못 낸 경우. 빈 카드를 띄우면 "중립 판단" 으로 읽힌다.
        AtomicReference<EarningsSummaryPublisher.Payload> published = new AtomicReference<>();
        EarningsSummaryModels.AnalyzeResponse blank = new EarningsSummaryModels.AnalyzeResponse(
                new EarningsSummaryModels.Analysis(null, null, null, null, null, null, null, null, null),
                null);
        EarningsSummaryService service = new EarningsSummaryService(
                clientOf(Optional.of(blank), Optional.of(intelligenceResponse())),
                capturingPublisher(published), priceCache(Map.of()));

        assertThat(service.summarizeAndPublish("ORCL", "call-1", SCRIPT)).isFalse();
        assertThat(published.get()).isNull();
    }

    @Test
    void 부가정보_조회_실패는_해당없음과_구분되어_실린다() {
        // 두 경우 모두 evasion/risk_plan 이 null 이라 페이로드에서 사라진다. 이 플래그가
        // 없으면 화면이 "조회 실패" 와 "엔진이 계획 없다고 답함" 을 구분할 수 없다.
        AtomicReference<EarningsSummaryPublisher.Payload> failed = new AtomicReference<>();
        new EarningsSummaryService(clientOf(Optional.of(analyzeResponse("BULLISH", 0.7)), Optional.empty()),
                capturingPublisher(failed), priceCache(Map.of()))
                .summarizeAndPublish("ORCL", "call-1", SCRIPT);

        AtomicReference<EarningsSummaryPublisher.Payload> ok = new AtomicReference<>();
        new EarningsSummaryService(
                clientOf(Optional.of(analyzeResponse("BULLISH", 0.7)), Optional.of(intelligenceResponse())),
                capturingPublisher(ok), priceCache(Map.of()))
                .summarizeAndPublish("ORCL", "call-1", SCRIPT);

        assertThat(failed.get().getIntelligenceAvailable()).isFalse();
        assertThat(ok.get().getIntelligenceAvailable()).isTrue();
    }

    @Test
    void PLACEHOLDER_QA_는_엔진에_보내지_않는다() {
        // 교체를 잊은 안내문을 그대로 보내면 엔진이 그 한국어 문장으로 회피 점수를 낸다.
        // 화면에는 의미 없는 숫자가 정상 지표처럼 뜬다 — 값이 없는 것보다 나쁘다.
        assertThat(EarningsSummaryService.usableQaText("PLACEHOLDER — 실제 질문으로 교체하세요.")).isNull();
        assertThat(EarningsSummaryService.usableQaText("   ")).isNull();
        assertThat(EarningsSummaryService.usableQaText(null)).isNull();
        assertThat(EarningsSummaryService.usableQaText(" capex 전망은? ")).isEqualTo("capex 전망은?");
    }

    @Test
    void QA_가_없으면_회피_지표를_페이로드에서_뺀다() {
        // 엔진은 Q&A 없이도 회피 점수 0.0 을 돌려준다. 그대로 실으면 화면에
        // "회피도 0%" 가 떠서 "질문을 전혀 피하지 않았다" 로 읽힌다.
        AtomicReference<EarningsSummaryPublisher.Payload> published = new AtomicReference<>();
        DemoEarningsCallScript noQa = new DemoEarningsCallScript(
                "ORCL", "Oracle", "Q4", "demo", List.of("NVDA"), null, SCRIPT.segments());

        new EarningsSummaryService(
                clientOf(Optional.of(analyzeResponse("BULLISH", 0.7)), Optional.of(intelligenceResponse())),
                capturingPublisher(published), priceCache(Map.of()))
                .summarizeAndPublish("ORCL", "call-1", noQa);

        assertThat(published.get().getEvasion()).isNull();
        // 회피만 빠지고 나머지 부가 정보는 그대로 실린다.
        assertThat(published.get().getRiskPlan()).isNotNull();
        assertThat(published.get().getIntelligenceAvailable()).isTrue();
    }

    @Test
    void 한쪽만_있는_QA_는_통째로_생략한다() {
        AtomicReference<EarningsSummaryModels.IntelligenceRequest> sent = new AtomicReference<>();
        DemoEarningsCallScript halfQa = new DemoEarningsCallScript(
                "ORCL", "Oracle", "Q4", "demo", List.of("NVDA"),
                new DemoEarningsCallScript.AnalystQa("capex 전망은?", "  "),
                SCRIPT.segments());
        AiEngineClient client = new AiEngineClient(null, true, true) {
            @Override
            public Optional<EarningsSummaryModels.AnalyzeResponse> analyze(
                    EarningsSummaryModels.AnalyzeRequest request) {
                return Optional.of(analyzeResponse("BULLISH", 0.7));
            }

            @Override
            public Optional<EarningsSummaryModels.IntelligenceResponse> earningsIntelligence(
                    EarningsSummaryModels.IntelligenceRequest request) {
                sent.set(request);
                return Optional.of(intelligenceResponse());
            }
        };
        new EarningsSummaryService(client, capturingPublisher(new AtomicReference<>()), priceCache(Map.of()))
                .summarizeAndPublish("ORCL", "call-1", halfQa);

        assertThat(sent.get().question()).isNull();
        assertThat(sent.get().answer()).isNull();
    }

    // ── 스텁 ────────────────────────────────────────────────────────────────

    private static EarningsSummaryModels.AnalyzeResponse analyzeResponse(String direction, double confidence) {
        return new EarningsSummaryModels.AnalyzeResponse(
                new EarningsSummaryModels.Analysis(direction, 0.85, confidence, "EARNINGS_GUIDANCE_UPGRADE",
                        "rationale", List.of("missing_rag_evidence"), 1, "gemini-3.6-flash", false),
                new EarningsSummaryModels.SignalBrief("AVOID", "soft_block", "tradable", "D", 48.06,
                        "research_only", "신규 진입 금지", "근거 부족", List.of("확인이 약합니다."), null, 1));
    }

    private static EarningsSummaryModels.IntelligenceResponse intelligenceResponse() {
        return new EarningsSummaryModels.IntelligenceResponse(
                new EarningsSummaryModels.OmissionEvasion(0.56, 0.44, 1.0, false,
                        List.of("capex", "margin"), "핵심 주제를 누락했습니다."),
                List.of(new EarningsSummaryModels.ImpactLink("NVDA", "supplier", "positive", 0.56, 0.45, "근거")),
                new EarningsSummaryModels.RiskPlan(true, "LONG", 242.5, 233.8, 254.0, 262.5,
                        4.1, 5.2, 8.3, 1.25, 3, "손절 이탈 시 무효", "분할 진입"),
                List.of("RAG evidence is empty"));
    }

    private static AiEngineClient clientOf(Optional<EarningsSummaryModels.AnalyzeResponse> analyze,
                                           Optional<EarningsSummaryModels.IntelligenceResponse> intel) {
        return new AiEngineClient(null, true, true) {
            @Override
            public Optional<EarningsSummaryModels.AnalyzeResponse> analyze(
                    EarningsSummaryModels.AnalyzeRequest request) {
                return analyze;
            }

            @Override
            public Optional<EarningsSummaryModels.IntelligenceResponse> earningsIntelligence(
                    EarningsSummaryModels.IntelligenceRequest request) {
                return intel;
            }
        };
    }

    private static EarningsSummaryPublisher capturingPublisher(
            AtomicReference<EarningsSummaryPublisher.Payload> sink) {
        return new EarningsSummaryPublisher(null) {
            @Override
            public void publish(Payload payload) {
                sink.set(payload);
            }
        };
    }

    private static StockPriceCache priceCache(Map<String, StockPriceSnapshot> snapshots) {
        return new StockPriceCache(null, null) {
            @Override
            public Map<String, StockPriceSnapshot> getAllAsMap() {
                return snapshots;
            }
        };
    }
}
