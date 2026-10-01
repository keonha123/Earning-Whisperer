package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.security.JwtProvider;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.support.ExecutorSubscribableChannel;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.messaging.StompSubProtocolHandler;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.Principal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 인증 실패 ERROR 프레임의 문구 계약 테스트.
 *
 * 터미널이 이 문구를 보고 액세스 토큰을 갱신한 뒤 재연결한다
 * ({@code trading-terminal/src/main/services/StompService.ts} 의 {@code STOMP_AUTH_ERROR}).
 *
 * 이 계약이 깨져도 양쪽 단위 테스트는 통과한다 — 인터셉터 테스트는 예외 메시지만 보고,
 * 터미널 테스트는 프레임을 손으로 만들기 때문이다. 그런데 깨지면 터미널은 만료된 토큰으로
 * 30초 간격 영구 재연결로 되돌아간다. 고치려던 증상 그 자체다.
 *
 * 그래서 실제 CONNECT 바이트를 흘려 소켓으로 나가는 ERROR 프레임을 직접 확인한다.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("STOMP 인증 실패 ERROR 프레임 계약")
class StompAuthErrorFrameContractTest {

    @Mock
    private JwtProvider jwtProvider;

    /** 소켓으로 나간 프레임을 모으는 세션. */
    private static final class RecordingSession implements WebSocketSession {
        private final List<String> sent = new ArrayList<>();
        private final Map<String, Object> attributes = new HashMap<>();
        private CloseStatus closeStatus;

        @Override
        public void sendMessage(WebSocketMessage<?> message) {
            sent.add(new String(((TextMessage) message).asBytes(), StandardCharsets.UTF_8));
        }

        @Override public String getId() { return "session-1"; }
        @Override public URI getUri() { return URI.create("ws://localhost/ws-native"); }
        @Override public org.springframework.http.HttpHeaders getHandshakeHeaders() {
            return new org.springframework.http.HttpHeaders();
        }
        @Override public Map<String, Object> getAttributes() { return attributes; }
        @Override public Principal getPrincipal() { return null; }
        @Override public InetSocketAddress getLocalAddress() { return null; }
        @Override public InetSocketAddress getRemoteAddress() { return null; }
        @Override public String getAcceptedProtocol() { return "v12.stomp"; }
        @Override public void setTextMessageSizeLimit(int messageSizeLimit) { }
        @Override public int getTextMessageSizeLimit() { return 8192; }
        @Override public void setBinaryMessageSizeLimit(int messageSizeLimit) { }
        @Override public int getBinaryMessageSizeLimit() { return 8192; }
        @Override public List<org.springframework.web.socket.WebSocketExtension> getExtensions() {
            return List.of();
        }
        @Override public boolean isOpen() { return closeStatus == null; }
        @Override public void close() { closeStatus = CloseStatus.NORMAL; }
        @Override public void close(CloseStatus status) { closeStatus = status; }
    }

    private String connectFrame(String authHeader) {
        String headers = authHeader == null ? "" : "Authorization:" + authHeader + "\n";
        return "CONNECT\naccept-version:1.2\nhost:localhost\n" + headers + "\n\u0000";
    }

    /** CONNECT 를 흘리고 소켓으로 나간 프레임을 돌려준다. */
    private List<String> handle(String frame) {
        ExecutorSubscribableChannel inbound = new ExecutorSubscribableChannel();
        inbound.addInterceptor(new StompJwtChannelInterceptor(jwtProvider));

        StompSubProtocolHandler handler = new StompSubProtocolHandler();
        RecordingSession session = new RecordingSession();
        handler.afterSessionStarted(session, inbound);
        handler.handleMessageFromClient(session, new TextMessage(frame), inbound);

        return session.sent;
    }

    @Test
    @DisplayName("토큰 없는 CONNECT 의 ERROR 프레임 message 헤더는 'STOMP 인증 실패' 다")
    void authFailureFrameCarriesAgreedMessage() {
        List<String> sent = handle(connectFrame(null));

        assertThat(sent).hasSize(1);
        String error = sent.get(0);
        assertThat(error).startsWith("ERROR\n");
        // 터미널의 STOMP_AUTH_ERROR 와 같아야 한다
        assertThat(error).contains("message:STOMP 인증 실패");
    }

    @Test
    @DisplayName("ERROR 프레임에 거부된 원본 프레임이 실리지 않는다")
    void errorFrameDoesNotLeakFailedMessage() {
        List<String> sent = handle(connectFrame("Bearer secret.jwt.token"));

        assertThat(sent).hasSize(1);
        // MessagingException 의 toString 에는 failedMessage 가 붙는다 — getMessage 를 써야 한다
        assertThat(sent.get(0)).doesNotContain("secret.jwt.token");
        assertThat(sent.get(0)).doesNotContain("failedMessage");
        // 내부 채널 빈 이름도 나가서는 안 된다
        assertThat(sent.get(0)).doesNotContain("clientInboundChannel");
    }
}
