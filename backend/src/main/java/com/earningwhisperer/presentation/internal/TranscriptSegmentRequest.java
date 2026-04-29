package com.earningwhisperer.presentation.internal;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * Contract 6.4 인입 페이로드 DTO.
 *
 * <p>snake_case ↔ camelCase 매핑은 {@link JsonProperty} 로 명시한다 (전역 PropertyNamingStrategy 미적용 환경 대비).
 * Bean Validation 으로 필수 필드를 강제한다 — 누락/공백 시 {@code GlobalExceptionHandler} 가 400 + JSON 으로 응답한다.
 *
 * <p>비즈니스 검증(시퀀스 단조성, 세션 종료 후 재인입)은 도메인 레이어가 담당한다.
 */
@Getter
@Setter
@NoArgsConstructor
public class TranscriptSegmentRequest {

    @NotBlank(message = "ticker는 필수입니다.")
    private String ticker;

    @NotBlank(message = "call_id는 필수입니다.")
    @JsonProperty("call_id")
    private String callId;

    @NotNull(message = "sequence는 필수입니다.")
    @PositiveOrZero(message = "sequence는 0 이상이어야 합니다.")
    private Integer sequence;

    @NotNull(message = "start_ms는 필수입니다.")
    @PositiveOrZero(message = "start_ms는 0 이상이어야 합니다.")
    @JsonProperty("start_ms")
    private Long startMs;

    @NotNull(message = "end_ms는 필수입니다.")
    @PositiveOrZero(message = "end_ms는 0 이상이어야 합니다.")
    @JsonProperty("end_ms")
    private Long endMs;

    @NotBlank(message = "text는 필수이며 비공백이어야 합니다.")
    private String text;

    /** 발화자 라벨. 선택 필드. */
    private String speaker;

    @NotNull(message = "timestamp는 필수입니다.")
    @PositiveOrZero(message = "timestamp는 0 이상이어야 합니다.")
    private Long timestamp;

    /** Boolean 객체로 받아 명시적 null 시 false 로 디폴트한다. */
    @JsonProperty("is_session_end")
    private Boolean isSessionEnd;

    /**
     * DTO → 도메인 record 변환.
     */
    public TranscriptSegment toDomain() {
        return new TranscriptSegment(
                ticker,
                callId,
                sequence,
                startMs,
                endMs,
                text,
                speaker,
                timestamp,
                Boolean.TRUE.equals(isSessionEnd)
        );
    }
}
