package com.earningwhisperer.global.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.EnableWebSocketMessageBroker;
import org.springframework.web.socket.config.annotation.StompEndpointRegistry;
import org.springframework.web.socket.config.annotation.WebSocketMessageBrokerConfigurer;

/**
 * WebSocket STOMP 설정.
 *
 * - 클라이언트 연결 엔드포인트: /ws (SockJS 폴백 지원)
 * - 메시지 브로커 prefix: /topic (구독용)
 * - 앱 목적지 prefix: /app (클라이언트 → 서버 메시지 전송용, 현재 미사용)
 *
 * 프론트엔드 구독 예시:
 *   stompClient.subscribe('/topic/live/NVDA', handler)
 */
@Configuration
@EnableWebSocketMessageBroker
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {

    @Override
    public void configureMessageBroker(MessageBrokerRegistry registry) {
        registry.enableSimpleBroker("/topic");
        registry.setApplicationDestinationPrefixes("/app");
    }

    @Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        registry.addEndpoint("/ws")
                .setAllowedOriginPatterns("*")
                .withSockJS();
    }
}
