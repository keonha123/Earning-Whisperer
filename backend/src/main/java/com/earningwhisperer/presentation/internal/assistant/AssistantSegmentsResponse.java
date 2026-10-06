package com.earningwhisperer.presentation.internal.assistant;

import com.earningwhisperer.domain.assistant.AssistantContextQueryService;
import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.util.List;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AssistantSegmentsResponse(String callId, int untilSequence, int lastSequence, List<Segment> segments) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Segment(int sequence, long startMs, long endMs, String speaker, String text, long timestamp) {
        static Segment from(TranscriptSegment s) {
            return new Segment(s.sequence(), s.startMs(), s.endMs(), s.speaker(), s.text(), s.timestamp());
        }
    }

    public static AssistantSegmentsResponse of(String callId, int untilSequence, AssistantContextQueryService.SegmentsView view) {
        return new AssistantSegmentsResponse(callId, untilSequence, view.lastSequence(),
                view.segments().stream().map(Segment::from).toList());
    }
}
