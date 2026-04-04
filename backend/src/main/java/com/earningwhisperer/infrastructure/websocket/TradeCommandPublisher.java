package com.earningwhisperer.infrastructure.websocket;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

/**
 * Trading Terminal로 매매 명령을 전송하는 Private WebSocket 퍼블리셔.
 *
 * convertAndSendToUser()는 Spring STOMP의 /user/{userId}/queue/signals 경로로 라우팅한다.
 * Principal.getName() = userId 문자열이 일치해야 전달된다.
 * (StompJwtChannelInterceptor가 CONNECT 시 Principal을 설정)
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TradeCommandPublisher {

    private static final String QUEUE_SIGNALS = "/queue/signals";

    private final SimpMessagingTemplate messagingTemplate;

    /**
     * @param userId  수신 대상 사용자 ID
     * @param message Contract 3b 규격의 매매 명령 메시지
     */
    public void publish(Long userId, TradeCommandMessage message) {
        String userIdStr = String.valueOf(userId);
        messagingTemplate.convertAndSendToUser(userIdStr, QUEUE_SIGNALS, message);
        log.info("[TradeCommand] 매매 명령 전송 - userId={} tradeId={} action={} ticker={}",
                userId, message.getTradeId(), message.getAction(), message.getTicker());
    }
}
