package com.earningwhisperer.domain.transcript;

import java.util.List;

/**
 * 진행 중인 콜의 세그먼트를 콜 단위로 쌓아 두는 저장소 포트.
 *
 * <p>backend 는 원래 세그먼트를 그대로 넘기기만 했다. 질의응답(#112)이 "지금까지의 콜" 을
 * 근거로 쓰려면 서버에 콜 단위 기록이 있어야 해서 추가했다. 발행 경로와는 격리되어,
 * 저장 실패가 자막 발행을 막지 않는다.
 */
public interface TranscriptSegmentStore {

    void append(TranscriptSegment segment);

    /** {@code untilSequence} 이하 세그먼트를 sequence 오름차순으로 돌려준다. 없으면 빈 목록. */
    List<TranscriptSegment> findUntil(String callId, int untilSequence);
}
