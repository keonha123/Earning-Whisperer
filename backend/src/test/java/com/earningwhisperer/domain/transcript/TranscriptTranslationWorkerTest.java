package com.earningwhisperer.domain.transcript;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.websocket.TranscriptPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import java.util.Optional;
import static org.mockito.Mockito.*;
class TranscriptTranslationWorkerTest {
    @Test void sendsMatchedTermsAndRejectsForeignIdentity() throws Exception {
        var client = mock(AiEngineClient.class);
        var publisher = mock(TranscriptPublisher.class);
        var glossary = new com.earningwhisperer.infrastructure.glossary.GlossaryService(new ObjectMapper(), "data/glossary_ko.json");
        var completed = new java.util.concurrent.CountDownLatch(1);
        when(client.transcriptRequest(anyString(), any())).thenAnswer(invocation -> {
            var body = (java.util.Map<?, ?>) invocation.getArgument(1);
            org.assertj.core.api.Assertions.assertThat(body.get("terms")).isEqualTo(java.util.List.of(
                    java.util.Map.of("term", "non-GAAP", "aliases", java.util.List.of(), "ko", "비GAAP")));
            completed.countDown();
            return Optional.of(new ObjectMapper().readTree("{\"available\":true,\"ticker\":\"OTHER\",\"call_id\":\"call\",\"sequence\":1,\"original_text\":\"non-GAAP\",\"text_ko\":\"비GAAP\"}"));
        });
        var worker = new TranscriptTranslationWorker(client, publisher, glossary, true);
        try {
            worker.submit(new TranscriptSegment("NVDA", "call", 1, 0, 100, "non-GAAP", null, 1700000000L, true));
            org.assertj.core.api.Assertions.assertThat(completed.await(2, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            verify(publisher, after(200).never()).publishTranslation(any(), anyString());
        } finally { worker.close(); }
    }
    @Test void publishesLateTranslationWithOriginalIdentity() throws Exception {
        var client = mock(AiEngineClient.class);
        var publisher = mock(TranscriptPublisher.class);
        var segment = new TranscriptSegment("NVDA", "call", 1, 0, 100, "Revenue grew", null, 1700000000L, true);
        when(client.transcriptRequest(anyString(), any())).thenReturn(Optional.of(new ObjectMapper().readTree(
                "{\"available\":true,\"ticker\":\"NVDA\",\"call_id\":\"call\",\"sequence\":1,\"original_text\":\"Revenue grew\",\"text_ko\":\"매출 증가\"}")));
        var glossary = new com.earningwhisperer.infrastructure.glossary.GlossaryService(new ObjectMapper(), "data/glossary_ko.json");
        var worker = new TranscriptTranslationWorker(client, publisher, glossary, true);
        try { worker.submit(segment); verify(publisher, timeout(2000)).publishTranslation(segment, "매출 증가"); }
        finally { worker.close(); }
    }
}
