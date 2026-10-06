package com.earningwhisperer.domain.transcript;

import com.earningwhisperer.infrastructure.aiengine.*;
import com.earningwhisperer.infrastructure.translation.TranscriptTranslationService;
import com.earningwhisperer.infrastructure.websocket.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import java.util.*;
import java.util.concurrent.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class LiveTranscriptFactCheckServiceTest {
    TranscriptSegment segment(int sequence, boolean end) {
        return new TranscriptSegment("NVDA", "live-call", sequence, 0, 1000, "Revenue increased", null, 1700000000L + sequence, end);
    }

    @Test void acceptedLiveSentencesAreOrderedAndPreserveEndCutoffAndReason() throws Exception {
        var registry = new TranscriptSessionRegistry();
        var transcriptPublisher = mock(TranscriptPublisher.class);
        var translation = mock(TranscriptTranslationService.class);
        var transcripts = new TranscriptService(registry, transcriptPublisher, translation);
        var client = mock(AiEngineClient.class);
        when(client.isFactCheckEnabled()).thenReturn(true);
        var publisher = new FactCheckPublisher(mock(SimpMessagingTemplate.class));
        ReflectionTestUtils.setField(publisher, "transcriptRegistry", registry);
        var requests = new CopyOnWriteArrayList<LiveFactCheckModels.SentenceRequest>();
        var finished = new CountDownLatch(3);
        var batch = new ObjectMapper().readValue("{\"ticker\":\"NVDA\",\"status\":\"COMPLETED\",\"batch_start_sequence\":0,\"batch_end_sequence\":2,\"claims\":[{\"source_text\":\"Revenue increased\",\"verdict\":\"INSUFFICIENT_EVIDENCE\",\"explanation_ko\":\"No matching evidence\"}]}", LiveFactCheckModels.BatchResponse.class);
        when(client.submitSentence(any())).thenAnswer(invocation -> {
            requests.add(invocation.getArgument(0)); finished.countDown(); return Optional.of(batch);
        });
        var live = new LiveTranscriptFactCheckService(transcripts, client, publisher);
        try {
            for (int i=0; i<3; i++) assertThat(live.accept(segment(i, i==2))).isEqualTo(TranscriptSessionRegistry.Result.OK);
            assertThat(live.accept(segment(3, false))).isEqualTo(TranscriptSessionRegistry.Result.SESSION_ENDED);
            assertThat(finished.await(3, TimeUnit.SECONDS)).isTrue();
            assertThat(requests).extracting(LiveFactCheckModels.SentenceRequest::sentenceSequence).containsExactly(0,1,2);
            assertThat(requests.get(2).isSessionEnd()).isTrue();
            assertThat(requests.get(2).callId()).isEqualTo("live-call");
            assertThat(requests.get(2).sentenceTimestamp()).isEqualTo(1700000002L);
            verify(transcriptPublisher, times(3)).publish(any());
            verify(translation, times(3)).submit(any());
            // Worker publication may finish just after submitSentence returns; join its lane with eventual assertion.
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
            while (registry.insufficientReason("NVDA", "live-call", List.of(2)).isEmpty() && System.nanoTime() < deadline) Thread.yield();
            assertThat(registry.insufficientReason("NVDA", "live-call", List.of(2))).isEqualTo("No matching evidence");
        } finally { live.close(); }
    }

    @Test void directDemoPathDoesNotSubmitTwiceAndRejectedLiveDoesNotSubmit() {
        var registry = new TranscriptSessionRegistry();
        var transcripts = new TranscriptService(registry, mock(TranscriptPublisher.class), mock(TranscriptTranslationService.class));
        var client = mock(AiEngineClient.class);
        var live = new LiveTranscriptFactCheckService(transcripts, client, mock(FactCheckPublisher.class));
        try {
            transcripts.accept(segment(0, false)); // Demo calls this common service and its own existing submit loop.
            assertThat(live.accept(segment(0, false))).isEqualTo(TranscriptSessionRegistry.Result.SEQ_REGRESS);
            verifyNoInteractions(client);
        } finally { live.close(); }
    }

    @Test void slowFactCheckNeverBlocksOriginalIngress() throws Exception {
        var registry = new TranscriptSessionRegistry();
        var publisher = mock(TranscriptPublisher.class);
        var transcripts = new TranscriptService(registry, publisher, mock(TranscriptTranslationService.class));
        var client = mock(AiEngineClient.class);
        when(client.isFactCheckEnabled()).thenReturn(true);
        var release = new CountDownLatch(1);
        when(client.submitSentence(any())).thenAnswer(i -> { release.await(2, TimeUnit.SECONDS); return Optional.empty(); });
        var live = new LiveTranscriptFactCheckService(transcripts, client, mock(FactCheckPublisher.class));
        try {
            live.accept(segment(0, false));
            live.accept(segment(1, true));
            verify(publisher, times(2)).publish(any());
            assertThat(release.getCount()).isEqualTo(1); // ingress completed before releasing the AI response
        } finally { release.countDown(); live.close(); }
    }
}
