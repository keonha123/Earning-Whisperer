package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.aiengine.LiveFactCheckModels;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 실시간 어닝콜 팩트체크 결과를 STOMP 토픽으로 fan-out 한다 (Contract 9.2).
 *
 * <pre>
 *   Topic   : /topic/factcheck/{ticker}
 *   Payload : ticker, call_id, batch_start_sequence, batch_end_sequence, claims[]
 * </pre>
 *
 * <p>{@link TranscriptPublisher} 와 동일한 정책을 따른다 — 발행 실패는 로깅만 하고
 * 예외를 재던지지 않는다. 팩트체크 카드 한 장 때문에 재생 루프가 멈추면 안 된다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FactCheckPublisher {

    static final String TOPIC_PREFIX = "/topic/factcheck/";

    private final SimpMessagingTemplate messagingTemplate;

    /**
     * 검증 완료된 배치를 발행한다. claims 가 비어 있으면 아무것도 하지 않는다.
     * (BUFFERING/REJECTED/DISCARDED 는 화면에 보여줄 것이 없다.)
     */
    public void publish(String ticker, String callId, LiveFactCheckModels.BatchResponse batch) {
        if (batch == null || !batch.isCompleted() || !batch.hasClaims()) {
            return;
        }
        String topic = TOPIC_PREFIX + ticker;
        Payload payload = Payload.builder()
                .ticker(ticker)
                .callId(callId)
                .batchStartSequence(batch.batchStartSequence())
                .batchEndSequence(batch.batchEndSequence())
                .claims(batch.claims())
                .build();
        try {
            messagingTemplate.convertAndSend(topic, payload);
            log.debug("[WebSocket] 팩트체크 fan-out - ticker={} call_id={} claims={}",
                    ticker, callId, batch.claims().size());
        } catch (Exception e) {
            log.error("STOMP 팩트체크 fan-out 실패 - ticker={}, call_id={}, error={}",
                    ticker, callId, e.getMessage(), e);
        }
    }

    /** STOMP 직렬화 전용 페이로드. 필드명은 Contract 9 에 맞춰 snake_case 로 내보낸다. */
    @Getter
    @Builder
    public static class Payload {
        private final String ticker;

        @JsonProperty("call_id")
        private final String callId;

        @JsonProperty("batch_start_sequence")
        private final Integer batchStartSequence;

        @JsonProperty("batch_end_sequence")
        private final Integer batchEndSequence;

        private final List<LiveFactCheckModels.Claim> claims;
    }
}
