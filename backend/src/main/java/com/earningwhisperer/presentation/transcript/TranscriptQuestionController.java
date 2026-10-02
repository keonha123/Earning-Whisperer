package com.earningwhisperer.presentation.transcript;
import com.earningwhisperer.domain.transcript.*;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.time.Instant;
import java.util.*;

/** Uses default JWT authenticated security rule. Clients supply identities, never evidence text. */
@RestController
@RequestMapping("/api/v1/transcript")
@RequiredArgsConstructor
public class TranscriptQuestionController {
    private final TranscriptSessionRegistry registry;
    private final AiEngineClient client;
    public record Question(@NotBlank String ticker, @NotBlank @JsonProperty("call_id") String callId,
            @NotEmpty @Size(max=10) @JsonProperty("segment_sequences") List<@NotNull @PositiveOrZero Integer> sequences,
            @NotBlank @Size(max=2000) String question) {}
    @GetMapping("/glossary") public JsonNode glossary() {
        return client.transcriptRequest("/v1/engine/glossary", null).orElseThrow(() -> new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE));
    }
    @PostMapping("/ask") public JsonNode ask(@Valid @RequestBody Question request) {
        List<TranscriptSegment> all = registry.completedSegments(request.ticker(), request.callId());
        if (all.isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT, "Completed session unavailable");
        Set<Integer> wanted = new HashSet<>(request.sequences());
        List<TranscriptSegment> selected = all.stream().filter(s -> wanted.contains(s.sequence())).toList();
        if (selected.size() != request.sequences().size()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unknown or duplicate segment");
        long asOf = selected.stream().mapToLong(TranscriptSegment::timestamp).max().orElseThrow();
        var body = Map.of("ticker", request.ticker(), "call_id", request.callId(),
                "segment_sequences", selected.stream().map(TranscriptSegment::sequence).toList(),
                "segment_texts", selected.stream().map(TranscriptSegment::text).toList(),
                "question", request.question(), "as_of", Instant.ofEpochSecond(asOf).toString(),
                "insufficient_reason", registry.insufficientReason(request.ticker(), request.callId(), request.sequences()));
        JsonNode response = client.transcriptRequest("/v1/engine/transcript/ask", body).orElseThrow(() ->
                new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Question service temporarily unavailable"));
        if (!response.path("ticker").asText().equals(request.ticker())
                || !response.path("call_id").asText().equals(request.callId())
                || !response.path("segment_sequences").equals(new com.fasterxml.jackson.databind.ObjectMapper().valueToTree(selected.stream().map(TranscriptSegment::sequence).toList())))
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Question response identity mismatch");
        return response;
    }
}
