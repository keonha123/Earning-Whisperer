package com.earningwhisperer.presentation.internal;

import com.earningwhisperer.domain.transcript.TranscriptSessionRegistry;
import com.earningwhisperer.domain.transcript.TranscriptService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Data Pipeline → Backend 인입 엔드포인트.
 *
 * <p>Contract 6.4 — POST {@code /api/v1/internal/transcript-segment}
 * <ul>
 *   <li>인증: {@code X-Internal-Secret} (InternalSecretFilter 가 401 처리)</li>
 *   <li>200 응답 대신 202 (Accepted) — 백엔드는 무상태 pass-through 이며 비동기 fan-out 의미를 살린다.</li>
 *   <li>400: 필수 필드 누락 / 형식 오류 / sequence 단조 위반</li>
 *   <li>409: is_session_end=true 이후 같은 call_id 재인입</li>
 * </ul>
 *
 * <p>에러 응답은 {@code GlobalExceptionHandler} 의 {@code {"error": "..."}} 형식과 동일하게 맞춘다.
 */
@RestController
@RequestMapping("/api/v1/internal")
@RequiredArgsConstructor
public class TranscriptInternalController {

    private final TranscriptService transcriptService;

    @PostMapping("/transcript-segment")
    public ResponseEntity<?> ingest(@Valid @RequestBody TranscriptSegmentRequest request) {
        TranscriptSessionRegistry.Result result = transcriptService.accept(request.toDomain());
        return switch (result) {
            case OK -> ResponseEntity.status(HttpStatus.ACCEPTED).build();
            case SEQ_REGRESS -> ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .body(Map.of("error", "sequence regress detected for call_id=" + request.getCallId()));
            case SESSION_ENDED -> ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "session already ended for call_id=" + request.getCallId()));
        };
    }
}
