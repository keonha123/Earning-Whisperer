package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 어닝콜 자막의 한국어 번역을 STOMP 토픽으로 fan-out 한다.
 *
 * <pre>
 *   Topic   : /topic/transcript-translation/{ticker}
 *   Payload : ticker, call_id, sequences[], text_ko, terms_used[]
 * </pre>
 *
 * <p>원문 자막({@code /topic/transcript/{ticker}})과 별도 토픽이다. 원문은 번역을 기다리지 않고
 * 바로 나가고, 번역은 몇 초 뒤 여러 세그먼트를 묶어 도착한다. 터미널은 {@code sequences} 로
 * 어느 자막들의 번역인지 짝짓는다.
 *
 * <p>{@link TranscriptDiffPublisher} 와 동일한 정책 — 발행 실패는 로깅만 하고 예외를 재던지지 않는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TranscriptTranslationPublisher {

    static final String TOPIC_PREFIX = "/topic/transcript-translation/";

    private final SimpMessagingTemplate messagingTemplate;

    public void publish(Payload payload) {
        String topic = TOPIC_PREFIX + payload.getTicker();
        try {
            messagingTemplate.convertAndSend(topic, payload);
            log.debug("[WebSocket] 번역 fan-out - ticker={} call_id={} sequences={}",
                    payload.getTicker(), payload.getCallId(), payload.getSequences());
        } catch (Exception e) {
            log.error("STOMP 번역 fan-out 실패 - ticker={}, call_id={}, sequences={}, error={}",
                    payload.getTicker(), payload.getCallId(), payload.getSequences(), e.getMessage(), e);
        }
    }

    /** STOMP 직렬화 전용 페이로드. 필드명은 다른 토픽과 맞춰 snake_case 로 내보낸다. */
    @Getter
    @Builder
    public static class Payload {
        private final String ticker;

        @JsonProperty("call_id")
        private final String callId;

        /** 이 번역이 담은 원문 세그먼트의 시퀀스. 오름차순이며 1개 이상이다. */
        private final List<Integer> sequences;

        @JsonProperty("text_ko")
        private final String textKo;

        /** 번역어를 고정한 용어 중 번역문에 실제로 들어간 것 (원문 표기). */
        @JsonProperty("terms_used")
        private final List<String> termsUsed;
    }
}
