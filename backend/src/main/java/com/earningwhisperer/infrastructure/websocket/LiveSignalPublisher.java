package com.earningwhisperer.infrastructure.websocket;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

/**
 * WebSocket STOMP 브로드캐스트 서비스.
 *
 * 계산 완료된 LiveSignalMessage를 /topic/live/{ticker} 토픽으로 전송한다.
 * 프론트엔드는 해당 토픽을 구독하여 실시간 신호를 수신한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class LiveSignalPublisher {

    private static final String TOPIC_PREFIX = "/topic/live/";

    private final SimpMessagingTemplate messagingTemplate;

    /**
     * @param message Contract 3 규격의 메시지 (ticker 필드 필수)
     */
    public void publish(LiveSignalMessage message) {
        String destination = TOPIC_PREFIX + message.getTicker();
        messagingTemplate.convertAndSend(destination, message);
        log.debug("[WebSocket] 브로드캐스트 - destination={} ticker={}", destination, message.getTicker());
    }
}
