package com.earningwhisperer.domain.transcript;

import com.earningwhisperer.infrastructure.websocket.TranscriptPublisher;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * 어닝콜 STT 세그먼트의 인입 → 검증 → fan-out 오케스트레이션 서비스.
 *
 * 책임:
 * <ul>
 *   <li>{@link TranscriptSessionRegistry} 에 위임해 sequence 단조성 / 세션 종료 여부 검증</li>
 *   <li>검증 통과 시에만 {@link TranscriptPublisher} 로 STOMP fan-out</li>
 * </ul>
 *
 * 검증 실패 시(=레지스트리가 OK 외 결과 반환) 컨트롤러가 적절한 HTTP 상태로 매핑할 수 있도록
 * Result enum 을 그대로 반환한다. 본 서비스는 HTTP 의존성이 없다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TranscriptService {

    private final TranscriptSessionRegistry registry;
    private final TranscriptPublisher publisher;

    /**
     * 세그먼트 인입을 처리한다.
     *
     * @return 레지스트리 검증 결과 (OK / SEQ_REGRESS / SESSION_ENDED)
     */
    public TranscriptSessionRegistry.Result accept(TranscriptSegment segment) {
        TranscriptSessionRegistry.Result result = registry.validateAndAccept(segment);
        if (result == TranscriptSessionRegistry.Result.OK) {
            publisher.publish(segment);
        } else {
            log.warn("[Transcript] 인입 거부 - ticker={} call_id={} sequence={} reason={}",
                    segment.ticker(), segment.callId(), segment.sequence(), result);
        }
        return result;
    }
}
