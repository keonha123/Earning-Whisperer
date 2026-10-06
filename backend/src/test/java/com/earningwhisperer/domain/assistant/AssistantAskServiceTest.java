package com.earningwhisperer.domain.assistant;

import com.earningwhisperer.domain.assistant.AssistantAskService.AskCommand;
import com.earningwhisperer.domain.assistant.AssistantAskService.HistoryTurn;
import com.earningwhisperer.domain.assistant.AssistantAskService.PreparedAsk;
import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptSegmentStore;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@DisplayName("AssistantAskService")
class AssistantAskServiceTest {

    @Mock TranscriptSegmentStore segmentStore;
    @InjectMocks AssistantAskService service;

    private static TranscriptSegment segment(int sequence, boolean end) {
        return new TranscriptSegment("WMT", "call-1", sequence, sequence * 6000L, sequence * 6000L + 5000,
                "text " + sequence, "CEO", 1_787_227_200L + sequence * 6L, end);
    }

    private static AskCommand command(int asOf, Integer anchor, String suggested) {
        return new AskCommand(7L, "wmt", "call-1", asOf, anchor, "가이던스가 바뀌었어?", suggested,
                List.of(new HistoryTurn("user", "앞 질문")));
    }

    @Test
    @DisplayName("저장된 마지막 세그먼트로 as_of 를 낮추고 그 시각을 as_of_epoch 로 쓴다")
    void clipsAsOfToStoredSegments() {
        when(segmentStore.findUntil("call-1", 20)).thenReturn(List.of(segment(1, false), segment(2, false), segment(5, false)));

        PreparedAsk prepared = service.prepare(command(20, 2, null));

        assertThat(prepared.asOfSequence()).isEqualTo(5);
        assertThat(prepared.asOfEpoch()).isEqualTo(1_787_227_230L);
        assertThat(prepared.ticker()).isEqualTo("WMT");
        assertThat(prepared.anchorSequence()).isEqualTo(2);
        assertThat(prepared.callEnded()).isFalse();
        assertThat(prepared.userId()).isEqualTo(7L);
        assertThat(prepared.history()).containsExactly(new HistoryTurn("user", "앞 질문"));
    }

    @Test
    @DisplayName("세그먼트가 없으면 SEGMENTS_NOT_FOUND")
    void noSegments() {
        when(segmentStore.findUntil("call-1", 3)).thenReturn(List.of());

        assertThatThrownBy(() -> service.prepare(command(3, null, null)))
                .isInstanceOf(AssistantAskException.class)
                .extracting("reason").isEqualTo(AssistantAskException.Reason.SEGMENTS_NOT_FOUND);
    }

    @Test
    @DisplayName("요청 ticker 가 저장된 콜의 ticker 와 다르면 TICKER_MISMATCH")
    void tickerMismatch() {
        when(segmentStore.findUntil("call-1", 3)).thenReturn(List.of(segment(1, false)));
        AskCommand other = new AskCommand(7L, "NVDA", "call-1", 3, null, "q", null, List.of());

        assertThatThrownBy(() -> service.prepare(other))
                .isInstanceOf(AssistantAskException.class)
                .extracting("reason").isEqualTo(AssistantAskException.Reason.TICKER_MISMATCH);
    }

    @Test
    @DisplayName("as_of 의 마지막 세그먼트가 종료 신호면 call_ended")
    void callEnded() {
        when(segmentStore.findUntil("call-1", 9)).thenReturn(List.of(segment(8, false), segment(9, true)));

        assertThat(service.prepare(command(9, null, null)).callEnded()).isTrue();
    }

    @Test
    @DisplayName("추천 질문이면 대목 지정을 버린다")
    void suggestedQuestionDropsAnchor() {
        when(segmentStore.findUntil("call-1", 3)).thenReturn(List.of(segment(1, false), segment(3, false)));

        PreparedAsk prepared = service.prepare(command(3, 1, "summary"));

        assertThat(prepared.anchorSequence()).isNull();
        assertThat(prepared.suggestedQuestionId()).isEqualTo("summary");
    }

    @Test
    @DisplayName("대목이 낮춘 as_of 보다 뒤면 버린다")
    void anchorAfterClippedAsOfIsDropped() {
        when(segmentStore.findUntil("call-1", 20)).thenReturn(List.of(segment(1, false), segment(5, false)));

        assertThat(service.prepare(command(20, 12, null)).anchorSequence()).isNull();
    }
}
