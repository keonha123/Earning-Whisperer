package com.earningwhisperer.infrastructure.demo;

import com.earningwhisperer.domain.stock.StockPriceSnapshot;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.aiengine.EarningsSummaryModels;
import com.earningwhisperer.infrastructure.websocket.EarningsSummaryPublisher;
import com.earningwhisperer.infrastructure.websocket.StockPriceCache;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * 어닝콜이 끝난 뒤 한 번 돌아가는 종합 판단 파이프.
 *
 * <p>실시간 팩트체크가 "지금 이 문장이 사실인가" 를 본다면, 여기서는 콜 전체를 놓고
 * "그래서 이 어닝콜을 어떻게 읽어야 하는가" 를 만든다. AI Engine 엔드포인트 두 개를
 * 순서대로 부른다 — 먼저 {@code analyze} 로 방향을 정하고, 그 방향을 힌트로 넘겨
 * {@code earnings/intelligence} 에서 손절 계획의 LONG/SHORT 를 가르게 한다.
 *
 * <p><b>실패해도 조용하지 않게.</b> 두 호출 모두 클라이언트가 실패를 흡수하므로
 * 여기서는 결과 유무로만 분기한다. 다만 판단 본문이 없으면 발행 자체를 건너뛰고
 * 이유를 로그로 남긴다. 빈 화면이 뜨는 것보다 "종합 판단 없음" 이 정확하다.
 */
@Slf4j
@Service
public class EarningsSummaryService {

    private final AiEngineClient aiEngineClient;
    private final EarningsSummaryPublisher publisher;
    private final StockPriceCache priceCache;

    public EarningsSummaryService(AiEngineClient aiEngineClient,
                                  EarningsSummaryPublisher publisher,
                                  StockPriceCache priceCache) {
        this.aiEngineClient = aiEngineClient;
        this.publisher = publisher;
        this.priceCache = priceCache;
    }

    /**
     * 종합 판단을 만들어 발행한다. 호출 스레드에서 동기로 돈다 — 재생 스레드가 아니라
     * 전용 스레드에서 부를 것.
     *
     * @param ticker  종목
     * @param callId  이번 재생 회차 식별자
     * @param script  재생한 스크립트. 전문·관련 종목·Q&A 를 여기서 꺼낸다.
     * @return 발행했으면 true
     */
    public boolean summarizeAndPublish(String ticker, String callId, DemoEarningsCallScript script) {
        if (!aiEngineClient.isSummaryEnabled()) {
            log.info("[Summary] 종합 판단 비활성화 - ticker={}", ticker);
            return false;
        }
        String transcript = joinTranscript(script);
        if (transcript.isBlank()) {
            log.warn("[Summary] 전문이 비어 종합 판단을 건너뜁니다 - ticker={} call_id={}", ticker, callId);
            return false;
        }

        Map<String, Object> marketData = marketData(ticker);

        Optional<EarningsSummaryModels.AnalyzeResponse> analyzed = aiEngineClient.analyze(
                new EarningsSummaryModels.AnalyzeRequest(ticker, transcript, true, marketData));
        if (analyzed.isEmpty() || !analyzed.get().hasAnalysis()) {
            log.warn("[Summary] 판단 본문을 받지 못해 발행하지 않습니다 - ticker={} call_id={}", ticker, callId);
            return false;
        }
        EarningsSummaryModels.Analysis judgment = analyzed.get().analysis();

        EarningsSummaryModels.IntelligenceRequest intelRequest =
                intelligenceRequest(ticker, transcript, script, marketData, judgment);
        Optional<EarningsSummaryModels.IntelligenceResponse> intel =
                aiEngineClient.earningsIntelligence(intelRequest);
        if (intel.isEmpty()) {
            // 조용히 넘기면 "회피 지표가 왜 안 뜨지" 를 조사할 때 어느 회차였는지 알 수 없다.
            log.warn("[Summary] 부가 정보 없이 판단만 발행합니다 - ticker={} call_id={}", ticker, callId);
        }
        intel.map(EarningsSummaryModels.IntelligenceResponse::riskPlan)
                .filter(plan -> plan.available() == null)
                .ifPresent(plan -> log.warn(
                        "[Summary] risk_plan.available 이 응답에 없습니다(엔진 응답 형식 변경 의심) "
                                + "- ticker={} call_id={}", ticker, callId));

        EarningsSummaryPublisher.Payload payload = EarningsSummaryPublisher.Payload.builder()
                .ticker(ticker)
                .callId(callId)
                .generatedAt(Instant.now().toString())
                .judgment(judgment)
                .gate(analyzed.get().signalBrief())
                // 부가 정보 4종은 한 덩어리다. 이 값이 false 면 "엔진이 해당 없음이라 답한 것"
                // 이 아니라 "조회 자체가 실패한 것" 이다. 화면이 둘을 구분할 수 있어야 한다.
                .intelligenceAvailable(intel.isPresent())
                // Q&A 를 안 보냈으면 엔진은 회피 점수 0.0 을 돌려준다. 그대로 내보내면
                // 화면에 "회피도 0%" 가 뜨고, 이건 "질문을 전혀 피하지 않았다" 로 읽힌다.
                // 분석을 안 한 것과 회피가 없는 것은 다른 이야기다.
                .evasion(intelRequest.question() == null
                        ? null
                        : intel.map(EarningsSummaryModels.IntelligenceResponse::omissionEvasion).orElse(null))
                .impactChain(intel.map(EarningsSummaryModels.IntelligenceResponse::impactChain).orElse(null))
                .riskPlan(intel.map(EarningsSummaryModels.IntelligenceResponse::riskPlan).orElse(null))
                .warnings(intel.map(EarningsSummaryModels.IntelligenceResponse::warnings).orElse(null))
                .build();
        publisher.publish(payload);
        return true;
    }

    private EarningsSummaryModels.IntelligenceRequest intelligenceRequest(
            String ticker,
            String transcript,
            DemoEarningsCallScript script,
            Map<String, Object> marketData,
            EarningsSummaryModels.Analysis judgment) {
        DemoEarningsCallScript.AnalystQa qa = script.analystQa();
        String question = usableQaText(qa == null ? null : qa.question());
        String answer = usableQaText(qa == null ? null : qa.answer());
        if (question == null || answer == null) {
            // 둘 중 하나만 있으면 회피 점수가 성립하지 않는다. 반쪽으로 보내면 엔진은
            // 그래도 숫자를 내고, 화면에는 의미 없는 값이 정상 지표처럼 뜬다.
            question = null;
            answer = null;
            log.info("[Summary] 애널리스트 Q&A 가 없어 회피 지표를 생략합니다 - ticker={}", ticker);
        }
        return new EarningsSummaryModels.IntelligenceRequest(
                ticker,
                transcript,
                question,
                answer,
                script.relatedTickers(),
                marketData,
                judgment.direction(),
                judgment.confidence());
    }

    /**
     * 쓸 수 있는 Q&A 텍스트만 통과시킨다.
     *
     * <p>공백은 물론 교체를 잊은 PLACEHOLDER 문구도 걸러 낸다. 스크립트의 안내문이 그대로
     * 질문으로 들어가면 엔진은 그 한국어 문장을 놓고 주제 누락을 계산해 그럴듯한 회피 점수를
     * 뱉는다. 틀린 값이 조용히 화면에 뜨는 것이 값이 없는 것보다 나쁘다.
     */
    static String usableQaText(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        String trimmed = text.trim();
        return trimmed.startsWith("PLACEHOLDER") ? null : trimmed;
    }

    /** 모든 세그먼트를 한 덩어리 텍스트로 잇는다. 엔진은 문장 단위 구분을 요구하지 않는다. */
    private String joinTranscript(DemoEarningsCallScript script) {
        List<DemoEarningsCallScript.Segment> segments = script.segments();
        if (segments == null) {
            return "";
        }
        return segments.stream()
                .map(DemoEarningsCallScript.Segment::text)
                .filter(text -> text != null && !text.isBlank())
                .collect(Collectors.joining(" "))
                .trim();
    }

    /**
     * 손절/익절 계산에 필요한 최소 가격 정보.
     *
     * <p>캐시에 종목이 없거나 가격이 0 이면 null 을 돌려준다. 엔진은 그 경우
     * {@code risk_plan.available=false} 와 사유를 돌려주므로, 없는 값을 지어내지 않는다.
     */
    private Map<String, Object> marketData(String ticker) {
        StockPriceSnapshot snapshot = priceCache.getAllAsMap().get(ticker);
        if (snapshot == null || snapshot.currentPrice() <= 0) {
            log.info("[Summary] 가격 정보가 없어 손절 계획은 생략됩니다 - ticker={}", ticker);
            return null;
        }
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("symbol", ticker);
        data.put("current_price", snapshot.currentPrice());
        if (snapshot.previousClose() > 0) {
            data.put("prev_close", snapshot.previousClose());
        }
        return data;
    }
}
