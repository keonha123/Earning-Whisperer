package com.earningwhisperer.presentation.internal;

import com.earningwhisperer.domain.transcript.TranscriptSessionRegistry;
import com.earningwhisperer.domain.transcript.TranscriptService;
import com.earningwhisperer.infrastructure.security.InternalSecretFilter;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * TranscriptInternalController 슬라이스 테스트.
 *
 * 검증:
 *   - 202: 정상 인입
 *   - 400: 필수 필드 누락 / sequence 단조 위반
 *   - 401: X-Internal-Secret 헤더 미일치 (InternalSecretFilter)
 *   - 409: is_session_end=true 이후 같은 call_id 재인입
 */
@WebMvcTest(TranscriptInternalController.class)
@Import({
        com.earningwhisperer.global.config.SecurityConfig.class,
        com.earningwhisperer.global.exception.GlobalExceptionHandler.class,
        InternalSecretFilter.class
})
@TestPropertySource(properties = "app.internal.secret=test-secret-value")
@DisplayName("TranscriptInternalController 슬라이스 테스트")
class TranscriptInternalControllerTest {

    @Autowired MockMvc mockMvc;
    @Autowired ObjectMapper objectMapper;

    @MockBean TranscriptService transcriptService;
    @MockBean com.earningwhisperer.infrastructure.security.JwtProvider jwtProvider;
    @MockBean com.earningwhisperer.infrastructure.security.UserDetailsServiceImpl userDetailsService;

    private static final String URL = "/api/v1/internal/transcript-segment";
    private static final String SECRET = "test-secret-value";

    /**
     * 9필드 모두 채운 정상 요청 본문을 생성한다.
     */
    private ObjectNode validBody() {
        ObjectNode body = objectMapper.createObjectNode();
        body.put("ticker", "NVDA");
        body.put("call_id", "earnings-2026Q1-NVDA");
        body.put("sequence", 0);
        body.put("start_ms", 0L);
        body.put("end_ms", 1500L);
        body.put("text", "Welcome to our quarterly call.");
        body.put("speaker", "CEO");
        body.put("timestamp", 1745000000L);
        body.put("is_session_end", false);
        return body;
    }

    @Test
    @DisplayName("정상 인입 — 202 Accepted")
    void 정상_202() throws Exception {
        when(transcriptService.accept(any())).thenReturn(TranscriptSessionRegistry.Result.OK);

        mockMvc.perform(post(URL)
                        .header("X-Internal-Secret", SECRET)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validBody())))
                .andExpect(status().isAccepted());

        verify(transcriptService).accept(any());
    }

    @Test
    @DisplayName("필수 필드 누락(text) — 400")
    void 필수_누락_400() throws Exception {
        ObjectNode body = validBody();
        body.remove("text");

        mockMvc.perform(post(URL)
                        .header("X-Internal-Secret", SECRET)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").exists());

        verify(transcriptService, never()).accept(any());
    }

    @Test
    @DisplayName("필수 필드 누락(call_id) — 400")
    void call_id_누락_400() throws Exception {
        ObjectNode body = validBody();
        body.remove("call_id");

        mockMvc.perform(post(URL)
                        .header("X-Internal-Secret", SECRET)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").exists());
    }

    @Test
    @DisplayName("text 가 공백뿐이면 — 400 (NotBlank)")
    void text_공백_400() throws Exception {
        ObjectNode body = validBody();
        body.put("text", "   ");

        mockMvc.perform(post(URL)
                        .header("X-Internal-Secret", SECRET)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("도메인 검증 결과 SEQ_REGRESS — 400")
    void sequence_역행_400() throws Exception {
        when(transcriptService.accept(any())).thenReturn(TranscriptSessionRegistry.Result.SEQ_REGRESS);

        mockMvc.perform(post(URL)
                        .header("X-Internal-Secret", SECRET)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validBody())))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").exists());
    }

    @Test
    @DisplayName("X-Internal-Secret 미일치 — 401, 서비스 미호출")
    void 시크릿_미일치_401() throws Exception {
        mockMvc.perform(post(URL)
                        .header("X-Internal-Secret", "WRONG")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validBody())))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").exists());

        verify(transcriptService, never()).accept(any());
    }

    @Test
    @DisplayName("X-Internal-Secret 헤더 누락 — 401")
    void 시크릿_누락_401() throws Exception {
        mockMvc.perform(post(URL)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validBody())))
                .andExpect(status().isUnauthorized());

        verify(transcriptService, never()).accept(any());
    }

    @Test
    @DisplayName("도메인 검증 결과 SESSION_ENDED — 409")
    void 세션_종료후_재인입_409() throws Exception {
        when(transcriptService.accept(any())).thenReturn(TranscriptSessionRegistry.Result.SESSION_ENDED);

        mockMvc.perform(post(URL)
                        .header("X-Internal-Secret", SECRET)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(validBody())))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").exists());
    }
}
