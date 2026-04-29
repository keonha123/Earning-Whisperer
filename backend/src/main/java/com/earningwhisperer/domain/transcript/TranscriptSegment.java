package com.earningwhisperer.domain.transcript;

/**
 * 어닝콜 STT(faster-whisper) stabilized 세그먼트의 도메인 표현.
 *
 * Contract 6.4 (Data Pipeline → Backend) / 4.5 (Backend → Trading Terminal) 공통 페이로드 모델.
 * 백엔드는 무상태 pass-through 이므로 본 record 는 영속성 어노테이션을 갖지 않으며
 * 인입(컨트롤러 DTO) → 도메인 → 발행(STOMP 페이로드) 구간만 흐른다.
 *
 * 필드는 외부 계약과 의미가 1:1 매핑된다.
 *
 * @param ticker        어닝콜 대상 종목 심볼 (예: NVDA)
 * @param callId        어닝콜 세션 식별자 (한 어닝콜 = 한 callId)
 * @param sequence      세션 내 단조 증가 시퀀스 (Pipeline 기준)
 * @param startMs       세션 시작 기준 segment 시작 오프셋(ms)
 * @param endMs         세션 시작 기준 segment 종료 오프셋(ms)
 * @param text          stabilized 전사 텍스트 (비공백 보장)
 * @param speaker       발화자 라벨 (선택, null 허용)
 * @param timestamp     발행 시각 (Unix Epoch Second, UTC)
 * @param isSessionEnd  세션 종료 여부. true 이후 동일 callId 재발행 금지.
 */
public record TranscriptSegment(
        String ticker,
        String callId,
        int sequence,
        long startMs,
        long endMs,
        String text,
        String speaker,
        long timestamp,
        boolean isSessionEnd
) {
}
