package com.earningwhisperer.global.config;

import com.earningwhisperer.infrastructure.websocket.StompJwtChannelInterceptor;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.ChannelRegistration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.EnableWebSocketMessageBroker;
import org.springframework.web.socket.config.annotation.StompEndpointRegistry;
import org.springframework.web.socket.config.annotation.WebSocketMessageBrokerConfigurer;

/**
 * WebSocket STOMP 설정.
 *
 * - 클라이언트 연결 엔드포인트: /ws (SockJS 폴백 지원)
 * - 메시지 브로커 prefix: /topic (Public 브로드캐스트), /queue (Private 라우팅)
 * - 앱 목적지 prefix: /app (클라이언트 → 서버 메시지 전송용, 현재 미사용)
 *
 * 구독 예시:
 *   Public  → stompClient.subscribe('/topic/live/NVDA', handler)
 *   Private → stompClient.subscribe('/user/queue/signals', handler)  [Trading Terminal 전용]
 */
@Configuration
@EnableWebSocketMessageBroker
@RequiredArgsConstructor
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {

    private final StompJwtChannelInterceptor stompJwtChannelInterceptor;

    @Override
    public void configureMessageBroker(MessageBrokerRegistry registry) {
        registry.enableSimpleBroker("/topic", "/queue");
        registry.setApplicationDestinationPrefixes("/app");
        registry.setUserDestinationPrefix("/user");
    }

    @Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        // 브라우저 클라이언트용 (SockJS 폴백)
        registry.addEndpoint("/ws")
                .setAllowedOriginPatterns("*")
                .withSockJS();

        // Trading Terminal용 (native WebSocket, ws 패키지)
        registry.addEndpoint("/ws-native")
                .setAllowedOriginPatterns("*");
    }

    @Override
    public void configureClientInboundChannel(ChannelRegistration registration) {
        registration.interceptors(stompJwtChannelInterceptor);
    }
}
