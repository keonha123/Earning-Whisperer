package com.earningwhisperer.presentation.internal.assistant;

import com.earningwhisperer.domain.assistant.AssistantContextQueryService;
import com.earningwhisperer.infrastructure.glossary.Glossary;
import com.earningwhisperer.infrastructure.glossary.GlossaryService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * logothea-assistant → backend 근거 조회 (#112).
 *
 * <p>인증: {@code X-Internal-Secret} (InternalSecretFilter 가 /api/v1/internal/** 전체를 검증).
 * 에러 본문은 기존 internal 컨트롤러와 같은 {@code {"error": "..."}} 형식이다.
 */
@RestController
@RequestMapping("/api/v1/internal/assistant")
@RequiredArgsConstructor
public class AssistantInternalController {

    private final AssistantContextQueryService queryService;
    private final GlossaryService glossaryService;

    @GetMapping("/calls/{callId}/segments")
    public ResponseEntity<?> segments(@PathVariable String callId,
                                      @RequestParam("until_sequence") int untilSequence) {
        if (untilSequence < 0) {
            return ResponseEntity.badRequest().body(Map.of("error", "until_sequence must be >= 0"));
        }
        return queryService.segments(callId, untilSequence)
                .<ResponseEntity<?>>map(view -> ResponseEntity.ok(AssistantSegmentsResponse.of(callId, untilSequence, view)))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("error", "no stored segments for call_id=" + callId)));
    }

    @GetMapping("/stocks/{ticker}/estimates")
    public ResponseEntity<?> estimates(@PathVariable String ticker,
                                       @RequestParam("as_of_epoch") long asOfEpoch) {
        return queryService.estimates(ticker, asOfEpoch)
                .<ResponseEntity<?>>map(view -> ResponseEntity.ok(AssistantEstimatesResponse.of(asOfEpoch, view)))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("error", "unknown ticker=" + ticker)));
    }

    @GetMapping("/glossary")
    public ResponseEntity<Glossary> glossary() {
        return ResponseEntity.ok(glossaryService.glossary());
    }
}
