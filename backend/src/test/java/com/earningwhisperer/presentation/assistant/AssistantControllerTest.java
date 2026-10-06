package com.earningwhisperer.presentation.assistant;

import com.earningwhisperer.domain.assistant.AssistantAskException;
import com.earningwhisperer.domain.assistant.AssistantAskService;
import com.earningwhisperer.domain.assistant.AssistantAskService.PreparedAsk;
import com.earningwhisperer.domain.assistant.AssistantQuota;
import com.earningwhisperer.global.config.AssistantProperties;
import com.earningwhisperer.infrastructure.security.InternalSecretFilter;
import com.earningwhisperer.infrastructure.security.JwtProvider;
import com.earningwhisperer.infrastructure.security.UserDetailsServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.RejectedExecutionException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 보안 필터를 포함한 슬라이스 테스트. SSE 가 끝날 때의 ASYNC 디스패치가 인증 오류로 바뀌지 않는지,
 * 터미널의 Accept 헤더로도 오류 JSON 이 406 으로 바뀌지 않는지를 함께 본다.
 */
@WebMvcTest(AssistantController.class)
@Import({
        com.earningwhisperer.global.config.SecurityConfig.class,
        com.earningwhisperer.global.exception.GlobalExceptionHandler.class,
        InternalSecretFilter.class,
        AssistantControllerTest.Config.class
})
@TestPropertySource(properties = "app.internal.secret=test-secret-value")
@DisplayName("AssistantController")
class AssistantControllerTest {

    @TestConfiguration
    static class Config {
        @Bean
        AssistantProperties assistantProperties() {
            return new AssistantProperties("http://127.0.0.1:8100", 50, 60);
        }
    }

    @Autowired MockMvc mockMvc;

    @MockBean AssistantAskService askService;
    @MockBean AssistantQuota quota;
    @MockBean AssistantRelay relay;
    @MockBean JwtProvider jwtProvider;
    @MockBean UserDetailsServiceImpl userDetailsService;

    private static final String URL = "/api/v1/assistant/ask";
    private static final String ACCEPT = "text/event-stream, application/json";
    private static final String BODY = """
            {"ticker": "WMT", "call_id": "call-1", "as_of_sequence": 17, "anchor_sequence": 3,
             "question": "  가이던스가 바뀌었어?  ", "suggested_question_id": null,
             "history": [{"role": "user", "text": "앞 질문"}, {"role": "assistant", "text": "앞 답"}]}
            """;
    private static final PreparedAsk PREPARED = new PreparedAsk(7L, "WMT", "call-1", 17, 1_787_227_218L, 3, false,
            "가이던스가 바뀌었어?", null, List.of());

    @BeforeEach
    void auth() {
        when(jwtProvider.validateToken("good")).thenReturn(true);
        when(jwtProvider.getUserIdFromToken("good")).thenReturn(7L);
    }

    private org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder ask(String body) {
        return post(URL).header("Authorization", "Bearer good").header("Accept", ACCEPT)
                .contentType(MediaType.APPLICATION_JSON).content(body);
    }

    @Test
    @DisplayName("JWT 가 없으면 401")
    void unauthenticated() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isUnauthorized());
        verify(askService, never()).prepare(any());
    }

    @Test
    @DisplayName("정상 요청은 SSE 로 중계하고, 끝날 때의 ASYNC 디스패치도 200 이다")
    void streams() throws Exception {
        when(askService.prepare(any())).thenReturn(PREPARED);
        when(quota.tryLock(eq(7L), any(Duration.class))).thenReturn(true);
        when(quota.tryConsumeDaily(eq(7L), any(), eq(50))).thenReturn(true);
        SseEmitter emitter = new SseEmitter(5_000L);
        when(relay.start(PREPARED)).thenReturn(emitter);

        MvcResult started = mockMvc.perform(ask(BODY)).andExpect(request().asyncStarted()).andReturn();
        emitter.send(SseEmitter.event().name("delta").data("{\"text\": \"매출\"}"));
        emitter.complete();

        mockMvc.perform(asyncDispatch(started))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("event:delta")));

        org.mockito.ArgumentCaptor<AssistantAskService.AskCommand> captor =
                org.mockito.ArgumentCaptor.forClass(AssistantAskService.AskCommand.class);
        verify(askService).prepare(captor.capture());
        AssistantAskService.AskCommand command = captor.getValue();
        assertThat(command.userId()).isEqualTo(7L);
        assertThat(command.question()).isEqualTo("가이던스가 바뀌었어?");
        assertThat(command.asOfSequence()).isEqualTo(17);
        assertThat(command.anchorSequence()).isEqualTo(3);
        assertThat(command.history()).hasSize(2);
    }

    @Test
    @DisplayName("세그먼트가 없으면 404 segments_not_found, 한도는 건드리지 않는다")
    void segmentsNotFound() throws Exception {
        when(askService.prepare(any())).thenThrow(new AssistantAskException(AssistantAskException.Reason.SEGMENTS_NOT_FOUND));

        mockMvc.perform(ask(BODY))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("segments_not_found"));
        verify(quota, never()).tryConsumeDaily(any(), any(), anyInt());
    }

    @Test
    @DisplayName("종목이 다르면 400 ticker_mismatch")
    void tickerMismatch() throws Exception {
        when(askService.prepare(any())).thenThrow(new AssistantAskException(AssistantAskException.Reason.TICKER_MISMATCH));

        mockMvc.perform(ask(BODY))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("ticker_mismatch"));
    }

    @Test
    @DisplayName("진행 중인 질문이 있으면 409 assistant_busy, 하루 횟수는 차감하지 않는다")
    void busy() throws Exception {
        when(askService.prepare(any())).thenReturn(PREPARED);
        when(quota.tryLock(eq(7L), any(Duration.class))).thenReturn(false);

        mockMvc.perform(ask(BODY))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("assistant_busy"));
        verify(quota, never()).tryConsumeDaily(any(), any(), anyInt());
    }

    @Test
    @DisplayName("하루 한도를 넘으면 429 와 다음 초기화 시각, 잠금은 푼다")
    void dailyLimit() throws Exception {
        when(askService.prepare(any())).thenReturn(PREPARED);
        when(quota.tryLock(eq(7L), any(Duration.class))).thenReturn(true);
        when(quota.tryConsumeDaily(eq(7L), any(), eq(50))).thenReturn(false);

        mockMvc.perform(ask(BODY))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$.code").value("daily_limit_exceeded"))
                .andExpect(jsonPath("$.reset_at").exists());
        verify(quota).unlock(7L);
    }

    @Test
    @DisplayName("중계 스레드풀이 가득 차면 503 assistant_overloaded")
    void overloaded() throws Exception {
        when(askService.prepare(any())).thenReturn(PREPARED);
        when(quota.tryLock(eq(7L), any(Duration.class))).thenReturn(true);
        when(quota.tryConsumeDaily(eq(7L), any(), eq(50))).thenReturn(true);
        when(relay.start(PREPARED)).thenThrow(new RejectedExecutionException("full"));

        mockMvc.perform(ask(BODY))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("assistant_overloaded"));
        // 중계가 이미 잠금을 풀므로 컨트롤러는 다시 풀지 않는다.
        verify(quota, never()).unlock(7L);
    }

    @Test
    @DisplayName("한도 확인 중 Redis 장애면 503 assistant_unavailable 이고 잠금은 푼다")
    void quotaFailureReleasesLock() throws Exception {
        when(askService.prepare(any())).thenReturn(PREPARED);
        when(quota.tryLock(eq(7L), any(Duration.class))).thenReturn(true);
        when(quota.tryConsumeDaily(eq(7L), any(), eq(50)))
                .thenThrow(new org.springframework.data.redis.RedisConnectionFailureException("down"));

        mockMvc.perform(ask(BODY))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("assistant_unavailable"));
        verify(quota).unlock(7L);
        verify(relay, never()).start(any());
    }

    @Test
    @DisplayName("Redis 장애면 503 assistant_unavailable")
    void redisDown() throws Exception {
        when(askService.prepare(any())).thenReturn(PREPARED);
        when(quota.tryLock(eq(7L), any(Duration.class)))
                .thenThrow(new org.springframework.data.redis.RedisConnectionFailureException("down"));

        mockMvc.perform(ask(BODY))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("assistant_unavailable"));
    }

    @Test
    @DisplayName("세그먼트 저장소 장애면 404 가 아니라 503 assistant_unavailable")
    void segmentStoreDown() throws Exception {
        when(askService.prepare(any()))
                .thenThrow(new org.springframework.data.redis.RedisConnectionFailureException("down"));

        mockMvc.perform(ask(BODY))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("assistant_unavailable"));
        verify(quota, never()).tryLock(any(), any());
    }

    @Test
    @DisplayName("질문 501자·대화 7개·잘못된 추천 질문 id·잘못된 역할은 400")
    void validation() throws Exception {
        String longQuestion = "가".repeat(501);
        mockMvc.perform(ask(BODY.replace("  가이던스가 바뀌었어?  ", longQuestion))).andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON));

        String sevenTurns = "[" + String.join(",", java.util.Collections.nCopies(7, "{\"role\": \"user\", \"text\": \"q\"}")) + "]";
        mockMvc.perform(ask(BODY.replaceFirst("\\[\\{\"role\".*\\]", sevenTurns))).andExpect(status().isBadRequest());

        mockMvc.perform(ask(BODY.replace("\"suggested_question_id\": null", "\"suggested_question_id\": \"buy_now\"")))
                .andExpect(status().isBadRequest());

        mockMvc.perform(ask(BODY.replace("\"role\": \"assistant\"", "\"role\": \"system\""))).andExpect(status().isBadRequest());

        mockMvc.perform(ask(BODY.replace("\"as_of_sequence\": 17", "\"as_of_sequence\": -1"))).andExpect(status().isBadRequest());

        verify(askService, never()).prepare(any());
    }
}
