package com.earningwhisperer.domain.transcript;

import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;

/**
 * 어닝콜 세션별 시퀀스 단조성 / 종료 여부를 추적하는 인메모리 레지스트리.
 *
 * <p>역할 (Contract 6.4 검증 책임):
 * <ul>
 *   <li>같은 callId 안에서 sequence 단조 증가(이전 sequence 이하 재인입 시 거부) 보장</li>
 *   <li>{@code is_session_end=true} 한 번 수신된 callId 재인입 시 거부 (409 신호)</li>
 *   <li>callId 간 격리 — 한 콜의 상태가 다른 콜에 영향을 주지 않는다.</li>
 * </ul>
 *
 * <p>동시성: callId별 {@link SessionState} 객체에 한해 synchronized 블록을 사용하여
 * 동일 callId 동시 인입을 직렬화하고, 서로 다른 callId 간에는 락을 공유하지 않는다.
 * 신규 SessionState 는 {@link ConcurrentHashMap#computeIfAbsent}로 원자적으로 생성한다.
 *
 * <p>TODO(미정): TTL/evict 정책 미적용 상태. 현재 구조상 callId 가 무한히 쌓이면 메모리 누수가
 * 발생할 수 있으므로 운영 단계에서 다음 중 하나를 도입해야 한다.
 * <ul>
 *   <li>{@code is_session_end=true} 수신 후 일정 시간 뒤 evict (지각 도착 재공격 방지)</li>
 *   <li>마지막 갱신 후 N시간 무활동 시 evict (스트림 끊김 대비)</li>
 *   <li>외부 캐시(Redis 등) 위임 — 다중 인스턴스 운영 시 필수</li>
 * </ul>
 */
@Component
public class TranscriptSessionRegistry {

    /**
     * callId 별 세션 상태. 키 무한 증가 가능성에 대한 운영 대응은 위 TODO 참조.
     */
    private final ConcurrentHashMap<String, SessionState> sessions = new ConcurrentHashMap<>();

    /**
     * 세그먼트 인입 검증 및 상태 갱신을 원자적으로 수행한다.
     *
     * <p>반환값 의미:
     * <ul>
     *   <li>{@link Result#OK} — 인입 허용. 레지스트리 상태가 갱신되었다.</li>
     *   <li>{@link Result#SEQ_REGRESS} — 같은 callId 의 lastSequence 이하 sequence 재인입.</li>
     *   <li>{@link Result#SESSION_ENDED} — is_session_end=true 가 이미 처리된 callId 재인입.</li>
     * </ul>
     */
    public Result validateAndAccept(TranscriptSegment segment) {
        SessionState state = sessions.computeIfAbsent(segment.callId(), k -> new SessionState());
        synchronized (state) {
            if (state.ended) {
                return Result.SESSION_ENDED;
            }
            if (state.lastSequence != null && segment.sequence() <= state.lastSequence) {
                return Result.SEQ_REGRESS;
            }
            state.lastSequence = segment.sequence();
            if (segment.isSessionEnd()) {
                state.ended = true;
            }
            return Result.OK;
        }
    }

    /**
     * 검증 결과 enum. 컨트롤러는 이 값을 HTTP 상태로 매핑한다.
     */
    public enum Result {
        OK,
        SEQ_REGRESS,
        SESSION_ENDED
    }

    /**
     * 세션별 상태. lastSequence 가 null 이면 첫 세그먼트 인입 전이다.
     * 본 클래스는 패키지 외부에서 직접 사용하지 않으므로 package-private 으로 둔다.
     */
    static final class SessionState {
        Integer lastSequence;
        boolean ended;
    }
}
