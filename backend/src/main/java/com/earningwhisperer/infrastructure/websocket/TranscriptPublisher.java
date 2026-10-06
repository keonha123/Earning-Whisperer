package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

/**
 * 어닝콜 STT 세그먼트를 STOMP 토픽으로 fan-out 한다.
 *
 * Contract 4.5 규격:
 *   Topic   : /topic/transcript/{ticker}
 *   Payload : ticker, call_id, sequence, start_ms, end_ms, text, speaker, timestamp, is_session_end
 *   Auth    : 구독 단계에서 StompJwtChannelInterceptor 가 검증 (본 클래스 책임 외)
 *
 * 정책: 인입은 무상태 pass-through 이므로 STOMP 발행 실패도 best-effort 로 흡수한다.
 *       MarketIndicesPublisher 와 동일한 시그니처/예외 처리 패턴을 따른다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TranscriptPublisher {

    static final String TOPIC_PREFIX = "/topic/transcript/";

    private final SimpMessagingTemplate messagingTemplate;

    /**
     * 세그먼트를 ticker 별 토픽으로 브로드캐스트한다.
     * 발행 실패는 로깅만 수행하고 예외를 재던지지 않는다.
     */
    public void publish(TranscriptSegment segment) {
        String topic = TOPIC_PREFIX + segment.ticker();
        Payload payload = Payload.from(segment);
        try {
            messagingTemplate.convertAndSend(topic, payload);
            log.debug("[WebSocket] 어닝콜 트랜스크립트 fan-out - ticker={} call_id={} sequence={} end={}",
                    payload.getTicker(), payload.getCallId(), payload.getSequence(), payload.isSessionEnd());
        } catch (Exception e) {
            // 인입은 무상태 pass-through. STOMP 실패는 로깅 후 재던지지 않는다.
            log.error("STOMP fan-out 실패 — ticker={}, call_id={}, sequence={}, error={}",
                    payload.getTicker(), payload.getCallId(), payload.getSequence(), e.getMessage(), e);
        }
    }

    /**
     * STOMP 직렬화 전용 페이로드.
     * Contract 6.4 / 4.5 의 9필드를 snake_case 로 직렬화한다.
     * speaker 는 선택 필드이므로 null 일 때 직렬화에서 제외한다.
     */
    @Getter
    @Builder
    public static class Payload {
        private final String ticker;

        @JsonProperty("call_id")
        private final String callId;

        private final int sequence;

        @JsonProperty("start_ms")
        private final long startMs;

        @JsonProperty("end_ms")
        private final long endMs;

        private final String text;

        @JsonInclude(JsonInclude.Include.NON_NULL)
        private final String speaker;

        private final long timestamp;

        /**
         * 필드명을 {@code sessionEnd} 로 두고 {@link JsonProperty} 로 snake_case 키를 강제한다.
         * 필드명을 {@code isSessionEnd} 로 두면 Lombok 이 {@code isSessionEnd()} getter 를 생성하여
         * Jackson 이 이를 {@code sessionEnd} 키로 추가 직렬화하는 충돌이 발생하므로 피한다.
         */
        @JsonProperty("is_session_end")
        private final boolean sessionEnd;

        static Payload from(TranscriptSegment segment) {
            return Payload.builder()
                    .ticker(segment.ticker())
                    .callId(segment.callId())
                    .sequence(segment.sequence())
                    .startMs(segment.startMs())
                    .endMs(segment.endMs())
                    .text(segment.text())
                    .speaker(segment.speaker())
                    .timestamp(segment.timestamp())
                    .sessionEnd(segment.isSessionEnd())
                    .build();
        }
    }
}
