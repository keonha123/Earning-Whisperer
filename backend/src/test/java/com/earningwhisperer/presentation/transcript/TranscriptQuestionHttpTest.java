package com.earningwhisperer.presentation.transcript;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.domain.transcript.TranscriptSessionRegistry;
import com.earningwhisperer.infrastructure.aiengine.AiEngineClient;
import com.earningwhisperer.infrastructure.security.InternalSecretFilter;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.web.servlet.MockMvc;
import java.util.List;
import java.util.Optional;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(TranscriptQuestionController.class)
@Import({com.earningwhisperer.global.config.SecurityConfig.class,
        com.earningwhisperer.global.exception.GlobalExceptionHandler.class, InternalSecretFilter.class})
class TranscriptQuestionHttpTest {
    @Autowired MockMvc mvc;
    @MockBean TranscriptSessionRegistry registry;
    @MockBean AiEngineClient client;
    @MockBean com.earningwhisperer.infrastructure.security.JwtProvider jwtProvider;
    private static final String BODY = "{\"ticker\":\"SMOKE\",\"call_id\":\"call\",\"segment_sequences\":[0],\"question\":\"Explain revenue\"}";
    @Test @WithMockUser void unavailableSessionIs409JsonWithoutErrorRedispatch() throws Exception {
        when(registry.completedSegments(anyString(), anyString())).thenReturn(List.of());
        mvc.perform(post("/api/v1/transcript/ask").contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isConflict()).andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("error").value("Completed session unavailable"));
        verifyNoInteractions(client);
    }
    @Test @WithMockUser void unknownSequenceIs400JsonWithoutErrorRedispatch() throws Exception {
        when(registry.completedSegments(anyString(), anyString())).thenReturn(List.of(
                new TranscriptSegment("SMOKE", "call", 9, 0, 1000, "Revenue grew", null, 1700000000L, true)));
        mvc.perform(post("/api/v1/transcript/ask").contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("error").value("Unknown or duplicate segment"));
        verifyNoInteractions(client);
    }
    @Test @WithMockUser void upstreamUnavailableIs503Json() throws Exception {
        when(registry.completedSegments(anyString(), anyString())).thenReturn(List.of(
                new TranscriptSegment("SMOKE", "call", 0, 0, 1000, "Revenue grew", null, 1700000000L, true)));
        when(registry.insufficientReason(anyString(), anyString(), anyList())).thenReturn("");
        when(client.transcriptRequest(anyString(), any())).thenReturn(Optional.empty());
        mvc.perform(post("/api/v1/transcript/ask").contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("error").value("Question service temporarily unavailable"));
    }
    @Test void unauthenticatedStill401() throws Exception {
        mvc.perform(post("/api/v1/transcript/ask").contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(registry, client);
    }
}
