package com.earningwhisperer.presentation.demo;

import com.earningwhisperer.infrastructure.demo.DemoEarningsCallService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Optional;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * DemoEarningsCallController 슬라이스 테스트.
 *
 * 서비스 결과 → HTTP 상태 매핑만 본다. 재생 동작은 DemoEarningsCallServiceTest 담당.
 * 보안 필터는 제외한다(인증 정책은 SecurityConfig 의 기본 규칙을 따르므로 별도 검증 대상).
 */
@WebMvcTest(controllers = DemoEarningsCallController.class,
        excludeAutoConfiguration = org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration.class)
@AutoConfigureMockMvc(addFilters = false)
@DisplayName("DemoEarningsCallController 슬라이스 테스트")
class DemoEarningsCallControllerTest {

    @Autowired MockMvc mockMvc;
    @MockBean DemoEarningsCallService service;

    @Test
    @DisplayName("시작 성공 시 202 와 call_id 를 반환한다")
    void start_202() throws Exception {
        when(service.start(any())).thenReturn(
                new DemoEarningsCallService.StartResult(
                        DemoEarningsCallService.StartResult.Outcome.STARTED,
                        "ORCL", "demo-orcl-1", 6, 6000, null, null));

        mockMvc.perform(post("/api/v1/demo/earnings-call/start")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"ticker\":\"ORCL\"}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.call_id").value("demo-orcl-1"))
                .andExpect(jsonPath("$.segment_count").value(6));
    }

    @Test
    @DisplayName("본문 없이 호출해도 스크립트 기본 종목으로 시작한다")
    void start_본문없음() throws Exception {
        when(service.start(null)).thenReturn(
                new DemoEarningsCallService.StartResult(
                        DemoEarningsCallService.StartResult.Outcome.STARTED,
                        "ORCL", "demo-orcl-2", 6, 6000, null, null));

        mockMvc.perform(post("/api/v1/demo/earnings-call/start"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.ticker").value("ORCL"));
    }

    @Test
    @DisplayName("이미 재생 중이면 409 를 반환한다")
    void start_409() throws Exception {
        when(service.start(any())).thenReturn(
                new DemoEarningsCallService.StartResult(
                        DemoEarningsCallService.StartResult.Outcome.ALREADY_RUNNING,
                        "ORCL", "demo-orcl-1", 0, 0, "이미 재생 중입니다. 먼저 중지하세요.", null));

        mockMvc.perform(post("/api/v1/demo/earnings-call/start")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"ticker\":\"ORCL\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").exists());
    }

    @Test
    @DisplayName("스크립트를 읽을 수 없으면 500 을 반환한다")
    void start_500() throws Exception {
        when(service.start(any())).thenReturn(
                new DemoEarningsCallService.StartResult(
                        DemoEarningsCallService.StartResult.Outcome.SCRIPT_UNAVAILABLE,
                        null, null, 0, 0, "스크립트 없음", null));

        mockMvc.perform(post("/api/v1/demo/earnings-call/start")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"ticker\":\"ORCL\"}"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error").value("스크립트 없음"));
    }

    @Test
    @DisplayName("진행 중인 재생이 없으면 중지는 404 를 반환한다")
    void stop_404() throws Exception {
        when(service.stop("ORCL")).thenReturn(false);

        mockMvc.perform(post("/api/v1/demo/earnings-call/stop")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"ticker\":\"ORCL\"}"))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("중지 성공 시 200 을 반환한다")
    void stop_200() throws Exception {
        when(service.stop("ORCL")).thenReturn(true);

        mockMvc.perform(post("/api/v1/demo/earnings-call/stop")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"ticker\":\"ORCL\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.stopped").value(true));
    }

    @Test
    @DisplayName("재생한 적 없는 종목의 상태는 running=false 만 반환한다")
    void status_미재생() throws Exception {
        when(service.status("ORCL")).thenReturn(Optional.empty());
        when(service.lastRun("ORCL")).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/v1/demo/earnings-call/status").param("ticker", "ORCL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.running").value(false))
                .andExpect(jsonPath("$.last_run").doesNotExist());
    }

    @Test
    @DisplayName("끝난 재생은 last_run 으로 결과를 알 수 있다")
    void status_종료후_결과() throws Exception {
        // "정상 완료" 와 "세그먼트를 하나도 못 내보내고 끝남" 이 구분되어야 한다.
        when(service.status("ORCL")).thenReturn(Optional.empty());
        when(service.lastRun("ORCL")).thenReturn(Optional.of(
                new DemoEarningsCallService.LastRun("ORCL", "demo-orcl-1",
                        "NO_SEGMENT_PUBLISHED", 0, 6)));

        mockMvc.perform(get("/api/v1/demo/earnings-call/status").param("ticker", "ORCL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.running").value(false))
                .andExpect(jsonPath("$.last_run.outcome").value("NO_SEGMENT_PUBLISHED"))
                .andExpect(jsonPath("$.last_run.published_count").value(0));
    }

    @Test
    @DisplayName("재생 중이면 진행 상황을 반환한다")
    void status_재생중() throws Exception {
        when(service.status("ORCL")).thenReturn(Optional.of(
                new DemoEarningsCallService.Status("ORCL", "demo-orcl-1", 3, 6)));

        mockMvc.perform(get("/api/v1/demo/earnings-call/status").param("ticker", "ORCL"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.running").value(true))
                .andExpect(jsonPath("$.published_count").value(3))
                .andExpect(jsonPath("$.total_segments").value(6));
    }
}
