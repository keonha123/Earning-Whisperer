package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.security.JwtProvider;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.MessageDeliveryException;
import org.springframework.messaging.simp.SimpMessageType;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.messaging.support.MessageHeaderAccessor;
import org.springframework.stereotype.Component;

import java.security.Principal;

/**
 * STOMP 인바운드 프레임을 인가하는 인터셉터.
 *
 * HTTP 필터 체인은 /ws/** 를 permitAll() 로 열어두므로, WebSocket 인증은 여기서만 이뤄진다.
 * 통과 여부를 결정하는 지점이 이 클래스 하나뿐이라는 뜻이다.
 *
 * 클라이언트는 STOMP CONNECT 헤더에 다음을 포함해야 한다:
 *   Authorization: Bearer {token}
 *
 * <h2>연결 프레임과 그 이후 프레임을 모두 본다</h2>
 *
 * 연결 프레임에서 토큰을 검증하고, 그 이후의 프레임은 Principal 이 실려 있는지로 판별한다.
 * 연결만 막는 것으로는 부족하기 때문이다 — Spring 의 {@code SimpleBrokerMessageHandler} 는
 * SUBSCRIBE 를 처리할 때 해당 세션이 CONNECT 를 거쳤는지 확인하지 않는다.
 *
 * <pre>
 * else if (SimpMessageType.SUBSCRIBE.equals(messageType)) {
 *     this.subscriptionRegistry.registerSubscription(message);   // 세션 조회 없음
 * }
 * </pre>
 *
 * 그래서 CONNECT 없이 SUBSCRIBE 한 프레임만 보내도 구독이 등록되고 브로드캐스트가 흐른다.
 * CONNECTED 응답을 못 받을 뿐 데이터는 받는다.
 *
 * Principal 로 판별할 수 있는 근거는 {@code StompSubProtocolHandler} 가 매 프레임마다
 * {@code headerAccessor.setUser(getUser(session))} 를 호출하고, 연결 때 저장해 둔 Principal 을
 * 돌려주기 때문이다. 즉 검증을 통과한 세션의 후속 프레임에는 Principal 이 반드시 실린다.
 *
 * 목적지 목록을 여기에 복제하지는 않는다. 토픽이 늘어날 때마다 양쪽을 맞춰야 하고,
 * 빠뜨린 토픽이 조용히 열리는 쪽으로 틀린다.
 *
 * <h2>클라이언트 SEND 는 받지 않는다</h2>
 *
 * 인가된 세션이라도 클라이언트가 서버로 보내는 SEND 프레임은 거부한다.
 * {@code DefaultUserDestinationResolver.parseMessage} 가 목적지의 {@code {userId}} 를
 * 그대로 믿고 그 사용자의 세션으로 라우팅하기 때문이다.
 *
 * <pre>
 * String userName = sourceDest.substring(prefixEnd, userEnd);
 * sessionIds = getSessionIdsByUser(userName, sessionId);
 * </pre>
 *
 * 즉 로그인한 사람 누구나 {@code /user/42/queue/signals} 로 위조 매매 신호를 밀어 넣을 수
 * 있고, 터미널이 AUTO_PILOT 이면 그대로 주문이 나간다. {@code /topic/**} 로 보내면 위조
 * 트랜스크립트·팩트체크를 방송할 수 있다.
 *
 * 목적지 allowlist 대신 전면 거부를 택한 이유는 쓰는 곳이 없기 때문이다 — 저장소에
 * {@code @MessageMapping} 과 {@code @SubscribeMapping} 이 0건이고, 터미널·웹 어디에도
 * {@code client.publish(} 가 없다. 서버→클라이언트 단방향 방송만 쓴다.
 *
 * <h2>사용자별 큐</h2>
 *
 * {@code convertAndSendToUser} 가 쓰는 {@code /user/} 목적지는 Spring 이 Principal 로 해석해
 * 내부적으로 {@code /queue/...-user{sessionId}} 로 바꾼다. Simple broker 에는 목적지 ACL 이
 * 없으므로 그 내부 이름을 직접 구독하면 닿기는 한다 — 막아 주는 것은 세션 ID 를 알 수 없다는
 * 점이다. 인가 자체는 이 인터셉터가 담당한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class StompJwtChannelInterceptor implements ChannelInterceptor {

    /**
     * 인증 실패로 거부할 때 ERROR 프레임에 실리는 문구.
     *
     * 터미널이 이 문구를 보고 액세스 토큰을 갱신한 뒤 재연결한다
     * ({@code trading-terminal/src/main/services/StompService.ts} 의 {@code STOMP_AUTH_ERROR}).
     * 바꾸면 그쪽도 함께 고쳐야 한다.
     */
    static final String AUTH_FAILED = "STOMP 인증 실패";

    /**
     * 인증과 무관한 거부에 쓰는 문구.
     *
     * 토큰을 갱신해도 달라지지 않는 거부를 {@link #AUTH_FAILED} 로 보내면
     * 터미널이 갱신과 재연결을 반복한다.
     */
    static final String NOT_ALLOWED = "허용되지 않는 STOMP 프레임";

    /**
     * 이 인터셉터가 직접 인증한 세션임을 나타내는 Principal.
     *
     * 후속 프레임의 인가를 "Principal 이 있다" 가 아니라 "이 인터셉터가 달았다" 로 판별하기
     * 위해 전용 타입을 쓴다. {@code StompSubProtocolHandler.getUser} 는 CONNECT 때 저장한
     * Principal 이 없으면 <b>핸드셰이크의 Principal</b> 로 넘어가기 때문이다.
     *
     * <pre>
     * Principal user = this.stompAuthentications.get(session.getId());
     * return (user != null ? user : session.getPrincipal());
     * </pre>
     *
     * 지금은 {@code JwtAuthenticationFilter} 가 Authorization 헤더만 보고 쿠키를 읽지 않아
     * 핸드셰이크에 Principal 이 실리지 않는다. 그래서 타입을 보지 않아도 안전하지만, 그 안전은
     * 이 인터셉터와 무관한 사실에 기대고 있다. 웹에서 쿠키 인증을 붙이는 순간 CONNECT 없는
     * SUBSCRIBE 가 조용히 다시 열린다.
     */
    record StompPrincipal(String name) implements Principal {
        @Override
        public String getName() {
            return name;
        }
    }

    private final JwtProvider jwtProvider;

    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
        StompHeaderAccessor accessor =
                MessageHeaderAccessor.getAccessor(message, StompHeaderAccessor.class);

        /*
         * accessor 가 없으면 프레임 종류를 알 수 없다. 통과시키면 인가가 통째로 건너뛰어지므로
         * 거부하는 쪽으로 둔다. 현재 경로에서는 StompDecoder 가 항상 mutable accessor 를 달아
         * 주므로 발생하지 않지만, 인바운드 채널에 메시지를 재생성하는 인터셉터가 이 앞에 끼면
         * null 이 될 수 있다. 그때 조용히 열리는 것보다 끊기는 편이 낫다.
         */
        if (accessor == null) {
            log.warn("[StompAuth] STOMP 헤더를 읽을 수 없어 거부한다");
            throw new MessageDeliveryException(message, AUTH_FAILED);
        }

        StompCommand command = accessor.getCommand();

        // 커맨드가 없는 프레임은 heartbeat 다. 연결이 이미 인가된 뒤에만 오간다.
        if (command == null) {
            return message;
        }

        /*
         * CONNECT 와 STOMP 는 STOMP 1.2 에서 같은 뜻이고 Spring 은 둘을 별개 enum 상수로
         * 디코딩한다. 커맨드를 직접 비교하면 STOMP 프레임이 검사를 빠져나가므로
         * Spring 내부와 같은 기준인 메시지 타입으로 본다.
         *
         *   STOMP(SimpMessageType.CONNECT),
         *   CONNECT(SimpMessageType.CONNECT),
         */
        if (SimpMessageType.CONNECT.equals(command.getMessageType())) {
            authenticateConnect(message, accessor);
            return message;
        }

        /*
         * DISCONNECT 는 인가하지 않는다. 인증 없이 보내도 자기 세션을 닫을 뿐이고,
         * 막으면 정상 종료 경로가 예외로 끝난다.
         */
        if (StompCommand.DISCONNECT.equals(command)) {
            return message;
        }

        if (!(accessor.getUser() instanceof StompPrincipal)) {
            log.warn("[StompAuth] 인가되지 않은 세션의 {} 프레임을 거부한다", command);
            throw new MessageDeliveryException(message, AUTH_FAILED);
        }

        /*
         * 인가된 세션이라도 SEND 는 받지 않는다. 사유를 인증 실패와 구분하는 이유는,
         * 터미널이 인증 실패 문구를 보면 토큰을 갱신하고 다시 붙기 때문이다 —
         * 토큰을 바꿔도 SEND 는 계속 거부되므로 갱신과 재연결을 반복하게 된다.
         */
        if (SimpMessageType.MESSAGE.equals(command.getMessageType())) {
            log.warn("[StompAuth] 클라이언트 SEND 는 허용하지 않는다 - destination={}",
                    accessor.getDestination());
            throw new MessageDeliveryException(message, NOT_ALLOWED);
        }

        return message;
    }

    private void authenticateConnect(Message<?> message, StompHeaderAccessor accessor) {
        String token = extractToken(accessor);
        if (token == null || !jwtProvider.validateToken(token)) {
            /*
             * 여기서 던지는 예외는 StompSubProtocolHandler 가 받아 ERROR 프레임으로 돌려주고
             * 세션을 닫는다. 클라이언트에는 onStompError 로 전달된다.
             *
             * 사유는 서버 로그에만 남긴다. ERROR 프레임 본문은 호출자에게 그대로 가므로
             * "토큰 없음" 과 "토큰 만료" 를 구분해 주면 탐색에 쓸 수 있다.
             */
            log.warn("[StompAuth] WebSocket 인증 실패 — 연결을 거부한다 (token={})",
                    token == null ? "없음" : "유효하지 않음");
            throw new MessageDeliveryException(message, AUTH_FAILED);
        }

        Long userId;
        try {
            userId = jwtProvider.getUserIdFromToken(token);
        } catch (RuntimeException e) {
            /*
             * 서명 검증을 통과한 토큰만 여기 닿으므로 sub 는 항상 userId 문자열이다.
             * 그래도 감싸 두는 이유는, MessagingException 이 아닌 예외가 올라가면
             * AbstractMessageChannel.send 가 채널 빈 이름을 담아 다시 감싸고
             * 그 문자열이 ERROR 프레임으로 나가기 때문이다.
             */
            log.warn("[StompAuth] 토큰에서 userId 를 읽지 못했다", e);
            throw new MessageDeliveryException(message, AUTH_FAILED);
        }

        // Principal.getName() = userId 문자열 → convertAndSendToUser(userId, ...) 와 매칭
        accessor.setUser(new StompPrincipal(String.valueOf(userId)));
        log.debug("[StompAuth] WebSocket 인증 성공 - userId={}", userId);
    }

    private String extractToken(StompHeaderAccessor accessor) {
        String auth = accessor.getFirstNativeHeader("Authorization");
        if (auth != null && auth.startsWith("Bearer ")) {
            String token = auth.substring(7);
            return token.isBlank() ? null : token;
        }
        return null;
    }
}
