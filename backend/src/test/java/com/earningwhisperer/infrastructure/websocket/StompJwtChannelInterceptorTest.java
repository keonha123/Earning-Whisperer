package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.security.JwtProvider;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageDeliveryException;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.messaging.support.MessageHeaderAccessor;

import java.security.Principal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * StompJwtChannelInterceptor 단위 테스트.
 *
 * 검증 포인트:
 *   1) 연결 프레임(CONNECT·STOMP)의 토큰 검증
 *   2) 연결 이후 프레임을 Principal 유무로 인가
 *   3) heartbeat·DISCONNECT 는 인가 대상에서 제외
 *   4) 헤더를 읽을 수 없는 프레임은 거부 (fail-closed)
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("StompJwtChannelInterceptor 단위 테스트")
class StompJwtChannelInterceptorTest {

    private static final String VALID_TOKEN = "valid.jwt.token";
    /**
     * 인터셉터가 CONNECT 에서 다는 Principal. 전용 타입이라 핸드셰이크 Principal 과 구분된다.
     */
    private static final Principal AUTHENTICATED =
            new StompJwtChannelInterceptor.StompPrincipal("42");

    /** 핸드셰이크에서 실릴 수 있는 Principal — 이 인터셉터가 단 것이 아니다. */
    private static final Principal HANDSHAKE_PRINCIPAL = () -> "42";

    @Mock
    private JwtProvider jwtProvider;

    @InjectMocks
    private StompJwtChannelInterceptor interceptor;

    /** 지정한 Authorization 헤더를 가진 프레임을 만든다. authHeader 가 null 이면 헤더를 넣지 않는다. */
    private Message<byte[]> frame(StompCommand command, String authHeader) {
        StompHeaderAccessor accessor = StompHeaderAccessor.create(command);
        if (authHeader != null) {
            accessor.addNativeHeader("Authorization", authHeader);
        }
        // StompDecoder.decodeMessage 가 실제 프레임에 하는 것과 같다
        accessor.setLeaveMutable(true);
        return MessageBuilder.createMessage(new byte[0], accessor.getMessageHeaders());
    }

    /** 연결을 통과한 세션의 후속 프레임. StompSubProtocolHandler 가 매 프레임에 Principal 을 싣는다. */
    private Message<byte[]> frameWithUser(StompCommand command, Principal user) {
        StompHeaderAccessor accessor = StompHeaderAccessor.create(command);
        accessor.setUser(user);
        accessor.setLeaveMutable(true);
        return MessageBuilder.createMessage(new byte[0], accessor.getMessageHeaders());
    }

    @Nested
    @DisplayName("연결 프레임")
    class ConnectFrames {

        @Test
        @DisplayName("토큰이 없는 CONNECT 는 거부한다")
        void rejectsConnectWithoutToken() {
            assertThatThrownBy(() -> interceptor.preSend(frame(StompCommand.CONNECT, null), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }

        @Test
        @DisplayName("토큰이 없는 STOMP 프레임도 거부한다")
        void rejectsStompFrameWithoutToken() {
            /*
             * STOMP 1.2 에서 STOMP 는 CONNECT 와 동의어이고 Spring 은 둘을 별개 enum 상수로
             * 디코딩한다. 커맨드를 직접 비교하면 이 프레임이 검사를 빠져나가 인증 없이
             * 세션이 수립된다.
             */
            assertThatThrownBy(() -> interceptor.preSend(frame(StompCommand.STOMP, null), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }

        @Test
        @DisplayName("유효하지 않은 토큰의 CONNECT 는 거부한다")
        void rejectsConnectWithInvalidToken() {
            when(jwtProvider.validateToken(anyString())).thenReturn(false);

            assertThatThrownBy(() ->
                    interceptor.preSend(frame(StompCommand.CONNECT, "Bearer expired.jwt.token"), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }

        @Test
        @DisplayName("Bearer 접두사가 없는 Authorization 헤더는 토큰으로 보지 않는다")
        void rejectsConnectWithoutBearerPrefix() {
            assertThatThrownBy(() ->
                    interceptor.preSend(frame(StompCommand.CONNECT, VALID_TOKEN), null))
                    .isInstanceOf(MessageDeliveryException.class);
        }

        @Test
        @DisplayName("Bearer 뒤가 비어 있으면 거부한다")
        void rejectsConnectWithBlankToken() {
            assertThatThrownBy(() ->
                    interceptor.preSend(frame(StompCommand.CONNECT, "Bearer "), null))
                    .isInstanceOf(MessageDeliveryException.class);
        }

        @Test
        @DisplayName("유효한 토큰의 CONNECT 는 통과하고 Principal 에 userId 를 담는다")
        void acceptsConnectWithValidToken() {
            when(jwtProvider.validateToken(VALID_TOKEN)).thenReturn(true);
            when(jwtProvider.getUserIdFromToken(VALID_TOKEN)).thenReturn(42L);

            Message<byte[]> connect = frame(StompCommand.CONNECT, "Bearer " + VALID_TOKEN);
            Message<?> result = interceptor.preSend(connect, null);

            assertThat(result).isNotNull();

            /*
             * 원본 메시지의 accessor 를 그대로 본다. 실제 동작은 mutable accessor 를
             * 제자리에서 고치는 것이라, 복사본을 검사하면 그 메커니즘을 검증하지 못한다.
             */
            StompHeaderAccessor original =
                    MessageHeaderAccessor.getAccessor(connect, StompHeaderAccessor.class);
            assertThat(original).isNotNull();
            // convertAndSendToUser(userId, ...) 와 매칭되려면 userId 문자열이어야 한다
            assertThat(original.getUser()).isNotNull();
            assertThat(original.getUser().getName()).isEqualTo("42");
        }

        @Test
        @DisplayName("유효한 토큰의 STOMP 프레임도 통과하고 Principal 을 단다")
        void acceptsStompFrameWithValidToken() {
            when(jwtProvider.validateToken(VALID_TOKEN)).thenReturn(true);
            when(jwtProvider.getUserIdFromToken(VALID_TOKEN)).thenReturn(42L);

            Message<byte[]> connect = frame(StompCommand.STOMP, "Bearer " + VALID_TOKEN);
            interceptor.preSend(connect, null);

            StompHeaderAccessor original =
                    MessageHeaderAccessor.getAccessor(connect, StompHeaderAccessor.class);
            assertThat(original).isNotNull();
            assertThat(original.getUser()).isInstanceOf(StompJwtChannelInterceptor.StompPrincipal.class);
            assertThat(original.getUser().getName()).isEqualTo("42");
        }

        @Test
        @DisplayName("핸드셰이크에서 Principal 이 실려 있어도 토큰 없는 CONNECT 는 거부한다")
        void rejectsConnectWithHandshakePrincipalButNoToken() {
            /*
             * StompSubProtocolHandler.getUser 는 CONNECT 때 저장한 Principal 이 없으면
             * 핸드셰이크의 Principal 로 넘어간다. 웹에서 쿠키 인증을 붙이면 /ws 핸드셰이크에
             * Principal 이 실릴 수 있는데, 그것으로 STOMP 인증을 대신해서는 안 된다.
             */
            assertThatThrownBy(() ->
                    interceptor.preSend(frameWithUser(StompCommand.CONNECT, HANDSHAKE_PRINCIPAL), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }

        @Test
        @DisplayName("토큰에서 userId 를 읽지 못하면 같은 사유로 거부한다")
        void rejectsConnectWhenUserIdUnreadable() {
            when(jwtProvider.validateToken(VALID_TOKEN)).thenReturn(true);
            when(jwtProvider.getUserIdFromToken(VALID_TOKEN))
                    .thenThrow(new NumberFormatException("sub 가 숫자가 아니다"));

            assertThatThrownBy(() ->
                    interceptor.preSend(frame(StompCommand.CONNECT, "Bearer " + VALID_TOKEN), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    // 채널 빈 이름이 ERROR 프레임으로 새지 않도록 여기서 수렴시킨다
                    .hasMessageContaining("STOMP 인증 실패");
        }
    }

    @Nested
    @DisplayName("연결 이후 프레임")
    class SubsequentFrames {

        @Test
        @DisplayName("인가되지 않은 세션의 SUBSCRIBE 는 거부한다")
        void rejectsSubscribeWithoutPrincipal() {
            /*
             * Spring 의 SimpleBrokerMessageHandler 는 SUBSCRIBE 를 처리할 때 그 세션이
             * CONNECT 를 거쳤는지 보지 않는다. 그래서 CONNECT 없이 SUBSCRIBE 만 보내도
             * 구독이 등록된다. 연결만 막아서는 부족하다.
             */
            assertThatThrownBy(() -> interceptor.preSend(frame(StompCommand.SUBSCRIBE, null), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }

        @Test
        @DisplayName("인가되지 않은 세션의 SEND 는 거부한다")
        void rejectsSendWithoutPrincipal() {
            assertThatThrownBy(() -> interceptor.preSend(frame(StompCommand.SEND, null), null))
                    .isInstanceOf(MessageDeliveryException.class);
        }

        @Test
        @DisplayName("인가된 세션의 SUBSCRIBE 는 통과시킨다")
        void acceptsSubscribeWithPrincipal() {
            assertThatCode(() ->
                    interceptor.preSend(frameWithUser(StompCommand.SUBSCRIBE, AUTHENTICATED), null))
                    .doesNotThrowAnyException();
        }

        @Test
        @DisplayName("핸드셰이크 Principal 만 있는 세션의 SUBSCRIBE 는 거부한다")
        void rejectsSubscribeWithHandshakePrincipal() {
            // 인가 근거는 "Principal 이 있다" 가 아니라 "이 인터셉터가 달았다" 여야 한다
            assertThatThrownBy(() ->
                    interceptor.preSend(frameWithUser(StompCommand.SUBSCRIBE, HANDSHAKE_PRINCIPAL), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }

        @Test
        @DisplayName("SUBSCRIBE 의 Authorization 헤더로는 인증되지 않는다")
        void doesNotAuthenticateOutsideConnect() {
            // 토큰을 받는 지점은 연결 프레임 하나뿐이다
            assertThatThrownBy(() ->
                    interceptor.preSend(frame(StompCommand.SUBSCRIBE, "Bearer " + VALID_TOKEN), null))
                    .isInstanceOf(MessageDeliveryException.class);
        }

        @Test
        @DisplayName("인가된 세션이라도 SEND 는 거부하고, 사유를 인증 실패와 구분한다")
        void rejectsSendEvenWhenAuthorized() {
            /*
             * DefaultUserDestinationResolver.parseMessage 가 목적지의 {userId} 를 그대로 믿어,
             * 로그인한 누구나 /user/42/queue/signals 로 위조 매매 신호를 보낼 수 있다.
             *
             * 사유를 인증 실패로 보내면 터미널이 토큰을 갱신하고 다시 붙는데, 토큰을 바꿔도
             * SEND 는 계속 거부되므로 갱신과 재연결을 반복하게 된다.
             */
            StompHeaderAccessor accessor = StompHeaderAccessor.create(StompCommand.SEND);
            accessor.setUser(AUTHENTICATED);
            accessor.setDestination("/user/42/queue/signals");
            accessor.setLeaveMutable(true);
            Message<byte[]> send =
                    MessageBuilder.createMessage(new byte[0], accessor.getMessageHeaders());

            assertThatThrownBy(() -> interceptor.preSend(send, null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("허용되지 않는 STOMP 프레임");
        }

        @ParameterizedTest
        @EnumSource(value = StompCommand.class,
                names = {"ACK", "NACK", "BEGIN", "COMMIT", "ABORT"})
        @DisplayName("인가되지 않은 세션의 그 밖의 커맨드도 모두 거부한다")
        void rejectsOtherCommandsWithoutPrincipal(StompCommand command) {
            // 지금은 fall-through 로 막히지만, "무해해 보이는 커맨드" 분기가 생기면 열린다
            assertThatThrownBy(() -> interceptor.preSend(frame(command, null), null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }

        @Test
        @DisplayName("DISCONNECT 는 인가 없이 통과시킨다")
        void passesDisconnect() {
            // 인증 없이 보내도 자기 세션을 닫을 뿐이고, 막으면 정상 종료가 예외로 끝난다
            assertThatCode(() -> interceptor.preSend(frame(StompCommand.DISCONNECT, null), null))
                    .doesNotThrowAnyException();
        }
    }

    @Nested
    @DisplayName("그 밖의 프레임")
    class OtherFrames {

        @Test
        @DisplayName("커맨드가 없는 heartbeat 는 통과시킨다")
        void passesHeartbeat() {
            Message<byte[]> heartbeat = MessageBuilder.createMessage(
                    new byte[0], StompHeaderAccessor.createForHeartbeat().getMessageHeaders());

            assertThatCode(() -> interceptor.preSend(heartbeat, null)).doesNotThrowAnyException();
        }

        @Test
        @DisplayName("STOMP 헤더를 읽을 수 없는 메시지는 거부한다")
        void rejectsMessageWithoutStompHeaders() {
            // 인가가 통째로 건너뛰어지는 경로다. 조용히 열리는 것보다 끊기는 편이 낫다
            Message<byte[]> plain = MessageBuilder.withPayload(new byte[0]).build();

            assertThatThrownBy(() -> interceptor.preSend(plain, null))
                    .isInstanceOf(MessageDeliveryException.class)
                    .hasMessageContaining("STOMP 인증 실패");
        }
    }
}
