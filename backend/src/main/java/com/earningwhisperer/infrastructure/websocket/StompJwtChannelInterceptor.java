package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.security.JwtProvider;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.messaging.support.MessageHeaderAccessor;
import org.springframework.stereotype.Component;

/**
 * STOMP CONNECT 프레임에서 JWT를 파싱하여 Principal을 설정하는 인터셉터.
 *
 * HTTP 필터 체인은 /ws/** 를 permitAll()로 열어두므로, WebSocket 연결 시
 * 별도로 인증 처리를 해야 convertAndSendToUser()가 올바른 사용자에게 전달된다.
 *
 * 클라이언트는 STOMP CONNECT 헤더에 다음을 포함해야 한다:
 *   Authorization: Bearer {token}
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class StompJwtChannelInterceptor implements ChannelInterceptor {

    private final JwtProvider jwtProvider;

    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
        StompHeaderAccessor accessor =
                MessageHeaderAccessor.getAccessor(message, StompHeaderAccessor.class);

        if (accessor != null && StompCommand.CONNECT.equals(accessor.getCommand())) {
            String token = extractToken(accessor);
            if (token != null && jwtProvider.validateToken(token)) {
                Long userId = jwtProvider.getUserIdFromToken(token);
                // Principal.getName() = userId 문자열 → convertAndSendToUser(userId, ...) 와 매칭
                accessor.setUser(() -> String.valueOf(userId));
                log.debug("[StompAuth] WebSocket 인증 성공 - userId={}", userId);
            } else {
                log.warn("[StompAuth] WebSocket 인증 실패 또는 토큰 없음 — 비인증 연결 허용");
            }
        }
        return message;
    }

    private String extractToken(StompHeaderAccessor accessor) {
        String auth = accessor.getFirstNativeHeader("Authorization");
        if (auth != null && auth.startsWith("Bearer ")) {
            return auth.substring(7);
        }
        return null;
    }
}
