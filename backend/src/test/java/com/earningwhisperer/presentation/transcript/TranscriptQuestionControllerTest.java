package com.earningwhisperer.presentation.transcript;
import com.earningwhisperer.domain.transcript.*;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class TranscriptQuestionControllerTest {
    TranscriptSessionRegistry registry = new TranscriptSessionRegistry();
    AiEngineClient client = mock(AiEngineClient.class);
    TranscriptQuestionController controller = new TranscriptQuestionController(registry, client);
    TranscriptSegment segment(int seq, boolean end) {
        return new TranscriptSegment("NVDA", "call", seq, 0, 1000, "Authoritative original", null, 1700000000L, end);
    }
    TranscriptQuestionController.Question question(String ticker, List<Integer> sequences) {
        return new TranscriptQuestionController.Question(ticker, "call", sequences, "What changed?");
    }
    @Test void rejectsLiveUnknownAndCrossTickerSelections() {
        registry.validateAndAccept(segment(1, false));
        assertThatThrownBy(() -> controller.ask(question("NVDA", List.of(1)))).isInstanceOf(ResponseStatusException.class);
        registry.validateAndAccept(segment(2, true));
        assertThatThrownBy(() -> controller.ask(question("AAPL", List.of(1)))).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> controller.ask(question("NVDA", List.of(99)))).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> controller.ask(question("NVDA", List.of(1,1)))).isInstanceOf(ResponseStatusException.class);
        verifyNoInteractions(client);
    }
    @Test void retainsActualInsufficientReasonOnlyForMatchingCallAndText() {
        registry.validateAndAccept(segment(1, true));
        registry.recordInsufficientReason("NVDA", "call", 1, 1, "Authoritative original", "No dated documents matched");
        assertThat(registry.insufficientReason("NVDA", "call", List.of(1))).isEqualTo("No dated documents matched");
        assertThat(registry.insufficientReason("AAPL", "call", List.of(1))).isEmpty();
        assertThat(registry.insufficientReason("NVDA", "call", List.of(99))).isEmpty();
    }

    @Test void rejectsUpstreamIdentityMismatch() throws Exception {
        registry.validateAndAccept(segment(1, true));
        when(client.transcriptRequest(anyString(), any())).thenReturn(Optional.of(new ObjectMapper().readTree(
                "{\"ticker\":\"AAPL\",\"call_id\":\"call\",\"segment_sequences\":[1]}")));
        assertThatThrownBy(() -> controller.ask(question("NVDA", List.of(1)))).isInstanceOf(ResponseStatusException.class);
    }

    @Test void forwardsAuthoritativeTextAndHistoricalCutoff() throws Exception {
        registry.validateAndAccept(segment(1, true));
        when(client.transcriptRequest(anyString(), any())).thenReturn(Optional.of(new ObjectMapper().readTree("{\"available\":false,\"ticker\":\"NVDA\",\"call_id\":\"call\",\"segment_sequences\":[1],\"evidence\":[]}")));
        controller.ask(question("NVDA", List.of(1)));
        ArgumentCaptor<Object> body = ArgumentCaptor.forClass(Object.class);
        verify(client).transcriptRequest(eq("/v1/engine/transcript/ask"), body.capture());
        Map<?,?> fields = (Map<?,?>) body.getValue();
        assertThat(fields.get("segment_texts")).isEqualTo(List.of("Authoritative original"));
        assertThat(fields.get("as_of")).isEqualTo("2023-11-14T22:13:20Z");
    }
}
