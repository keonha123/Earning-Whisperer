package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.aiengine.TranscriptDiffModels;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 직전 콜 발언과의 대조 결과를 STOMP 토픽으로 fan-out 한다.
 *
 * <pre>
 *   Topic   : /topic/transcript-diff/{ticker}
 *   Payload : ticker, call_id, sequence, previous_document, items[]
 * </pre>
 *
 * <p>팩트체크와 별도 토픽을 쓴다. 두 결과는 근거가 다르고(뉴스 / 직전 콜), 도착 시점도
 * 다르며, 화면에서 놓이는 자리도 다르다. 한 토픽에 섞으면 구독자가 매번 종류를 갈라야 한다.
 *
 * <p>{@link FactCheckPublisher} 와 동일한 정책 — 발행 실패는 로깅만 하고 예외를 재던지지
 * 않는다. 대조 카드 한 장 때문에 재생 루프가 멈추면 안 된다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TranscriptDiffPublisher {

    static final String TOPIC_PREFIX = "/topic/transcript-diff/";

    private final SimpMessagingTemplate messagingTemplate;

    /**
     * 대조 결과를 발행한다. 보여줄 항목이 없으면 아무것도 하지 않는다.
     *
     * <p>항목이 비는 경우가 정상 동작에 포함된다 — 주제와 무관한 발언
     * ({@code current_chunk_not_material})이 대부분이고, 매 발언마다 카드를 띄우는
     * 기능이 아니다. 사유를 화면에 흘리면 빈 카드가 계속 쌓인다.
     *
     * <p>다만 직전 콜 자체가 없는 경우({@code available=false})는 설정 문제이므로
     * 로그로 남긴다. 조용히 지나가면 시연 중에 왜 아무것도 안 나오는지 알 수 없다.
     */
    public void publish(String ticker, String callId, int sequence, TranscriptDiffModels.DiffResponse diff) {
        if (diff == null) {
            return;
        }
        if (!diff.available()) {
            log.warn("[WebSocket] 과거 콜 대조 불가 - ticker={} call_id={} sequence={} warnings={}",
                    ticker, callId, sequence, diff.warnings());
            return;
        }
        if (!diff.hasItems()) {
            return;
        }
        String topic = TOPIC_PREFIX + ticker;
        Payload payload = Payload.builder()
                .ticker(ticker)
                .callId(callId)
                .sequence(sequence)
                .previousDocument(diff.previousDocument())
                .items(diff.items())
                .build();
        try {
            messagingTemplate.convertAndSend(topic, payload);
            log.debug("[WebSocket] 과거 콜 대조 fan-out - ticker={} call_id={} sequence={} items={}",
                    ticker, callId, sequence, diff.items().size());
        } catch (Exception e) {
            log.error("STOMP 과거 콜 대조 fan-out 실패 - ticker={}, call_id={}, sequence={}, error={}",
                    ticker, callId, sequence, e.getMessage(), e);
        }
    }

    /** STOMP 직렬화 전용 페이로드. 필드명은 다른 토픽과 맞춰 snake_case 로 내보낸다. */
    @Getter
    @Builder
    public static class Payload {
        private final String ticker;

        @JsonProperty("call_id")
        private final String callId;

        /** 어느 발언에 대한 대조인지. 터미널이 해당 세그먼트와 짝지을 때 쓴다. */
        private final int sequence;

        @JsonProperty("previous_document")
        private final TranscriptDiffModels.PreviousDocument previousDocument;

        private final List<TranscriptDiffModels.DiffItem> items;
    }
}
