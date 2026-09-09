package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.aiengine.EarningsSummaryModels;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 어닝콜이 끝난 뒤의 종합 판단을 STOMP 토픽으로 발행한다 (Contract 4.7).
 *
 * <pre>
 *   Topic   : /topic/evaluation/{ticker}
 *   Payload : ticker, call_id, generated_at, judgment, gate, evasion, impact_chain, risk_plan, warnings
 * </pre>
 *
 * <p>회차당 한 번만 발행된다. 다른 publisher 들과 같은 정책으로, 발행 실패는 로깅만 하고
 * 예외를 재던지지 않는다.
 *
 * <p><b>judgment 와 gate 를 나눠 담는 이유.</b> 엔진의 {@code action} 은 방향이 아니라
 * "지금 이 판단대로 움직여도 되는가" 의 답이다. 근거가 부족하면 BULLISH 판단에도
 * AVOID 가 붙는다. 한 덩어리로 보내면 화면이 "강세인데 회피" 를 한 줄에 그리게 되고
 * 보는 사람은 시스템이 고장 난 것으로 읽는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EarningsSummaryPublisher {

    static final String TOPIC_PREFIX = "/topic/evaluation/";

    private final SimpMessagingTemplate messagingTemplate;

    public void publish(Payload payload) {
        String topic = TOPIC_PREFIX + payload.getTicker();
        try {
            messagingTemplate.convertAndSend(topic, payload);
            log.info("[WebSocket] 종합 판단 fan-out - ticker={} call_id={} direction={}",
                    payload.getTicker(), payload.getCallId(),
                    payload.getJudgment() == null ? null : payload.getJudgment().direction());
        } catch (Exception e) {
            log.error("STOMP 종합 판단 fan-out 실패 - ticker={}, call_id={}, error={}",
                    payload.getTicker(), payload.getCallId(), e.getMessage(), e);
        }
    }

    /** STOMP 직렬화 전용 페이로드. 필드명은 Contract 4.7 에 맞춰 snake_case 로 내보낸다. */
    @Getter
    @Builder
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Payload {
        private final String ticker;

        @JsonProperty("call_id")
        private final String callId;

        @JsonProperty("generated_at")
        private final String generatedAt;

        /** LLM 판단 본문. 이것이 null 이면 종합 화면을 그릴 수 없다. */
        private final EarningsSummaryModels.Analysis judgment;

        /** 실행 가능성 게이트. judgment 와 별개로 읽어야 한다. */
        private final EarningsSummaryModels.SignalBrief gate;

        /**
         * 부가 정보(회피·파급·손절) 조회 성공 여부.
         *
         * <p>이 필드가 없으면 화면이 "엔진이 계획 없음이라고 답한 경우" 와 "조회가 실패한
         * 경우" 를 구분할 수 없다. {@code NON_NULL} 직렬화 때문에 실패 시 네 필드가 통째로
         * 사라지는데, 그 모습이 "해당 없음" 과 똑같기 때문이다.
         */
        @JsonProperty("intelligence_available")
        private final Boolean intelligenceAvailable;

        private final EarningsSummaryModels.OmissionEvasion evasion;

        @JsonProperty("impact_chain")
        private final List<EarningsSummaryModels.ImpactLink> impactChain;

        @JsonProperty("risk_plan")
        private final EarningsSummaryModels.RiskPlan riskPlan;

        /**
         * 엔진이 붙인 주의사항. "RAG 근거가 비어 있어 휴리스틱 결과" 같은 것이 여기 온다.
         * 화면에서 숨기면 안 된다 — 검증되지 않은 판단을 검증된 것처럼 보이게 된다.
         */
        private final List<String> warnings;
    }
}
