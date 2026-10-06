package com.earningwhisperer.presentation.internal.assistant;

import com.earningwhisperer.domain.assistant.AssistantContextQueryService;
import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.earningwhisperer.infrastructure.glossary.Glossary;
import com.earningwhisperer.infrastructure.glossary.GlossaryService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** 응답 필드 이름(snake_case)과 404 분기만 본다. X-Internal-Secret 검증은 InternalSecretFilterTest 가 담당한다. */
@WebMvcTest(controllers = AssistantInternalController.class,
        excludeAutoConfiguration = org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration.class)
@AutoConfigureMockMvc(addFilters = false)
@DisplayName("AssistantInternalController 슬라이스 테스트")
class AssistantInternalControllerTest {

    @Autowired MockMvc mockMvc;
    @MockBean AssistantContextQueryService queryService;
    @MockBean GlossaryService glossaryService;

    @Test
    @DisplayName("세그먼트 조회는 snake_case 필드와 last_sequence 를 내려준다")
    void segments_200() throws Exception {
        TranscriptSegment s = new TranscriptSegment("WMT", "call-1", 3, 18_000, 23_000, "Comp sales were 2.6%.", "CEO", 1_787_227_218L, false);
        when(queryService.segments("call-1", 99)).thenReturn(Optional.of(new AssistantContextQueryService.SegmentsView(List.of(s), 3)));

        mockMvc.perform(get("/api/v1/internal/assistant/calls/call-1/segments").param("until_sequence", "99"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.call_id").value("call-1"))
                .andExpect(jsonPath("$.until_sequence").value(99))
                .andExpect(jsonPath("$.last_sequence").value(3))
                .andExpect(jsonPath("$.segments[0].sequence").value(3))
                .andExpect(jsonPath("$.segments[0].start_ms").value(18_000))
                .andExpect(jsonPath("$.segments[0].speaker").value("CEO"))
                .andExpect(jsonPath("$.segments[0].timestamp").value(1_787_227_218L));
    }

    @Test
    @DisplayName("저장된 세그먼트가 없으면 404")
    void segments_404() throws Exception {
        when(queryService.segments("none", 5)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/v1/internal/assistant/calls/none/segments").param("until_sequence", "5"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").exists());
    }

    @Test
    @DisplayName("until_sequence 가 음수면 400")
    void segments_400() throws Exception {
        mockMvc.perform(get("/api/v1/internal/assistant/calls/call-1/segments").param("until_sequence", "-1"))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("실적 추정치는 다음 일정과 최근 결과를 내려준다")
    void estimates_200() throws Exception {
        EarningsCalendar upcoming = mock(EarningsCalendar.class);
        when(upcoming.getScheduledAt()).thenReturn(Instant.parse("2026-08-20T11:00:00Z"));
        when(upcoming.getEpsEstimate()).thenReturn(new BigDecimal("0.7400"));
        when(upcoming.getRevenueEstimate()).thenReturn(new BigDecimal("176000000000.00"));
        EarningsResult result = mock(EarningsResult.class);
        when(result.getAnnouncedAt()).thenReturn(Instant.parse("2026-05-15T11:00:00Z"));
        when(result.getFiscalPeriodLabel()).thenReturn("Q1 FY27");
        when(result.getEpsActual()).thenReturn(new BigDecimal("0.6100"));
        when(queryService.estimates("WMT", 1_787_227_200L)).thenReturn(Optional.of(
                new AssistantContextQueryService.EstimatesView("WMT", Optional.of(upcoming), List.of(result))));

        mockMvc.perform(get("/api/v1/internal/assistant/stocks/WMT/estimates").param("as_of_epoch", "1787227200"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ticker").value("WMT"))
                .andExpect(jsonPath("$.as_of_epoch").value(1_787_227_200L))
                .andExpect(jsonPath("$.upcoming.eps_estimate").value(0.74))
                .andExpect(jsonPath("$.upcoming.scheduled_at").value("2026-08-20T11:00:00Z"))
                .andExpect(jsonPath("$.recent_results[0].fiscal_period_label").value("Q1 FY27"))
                .andExpect(jsonPath("$.recent_results[0].eps_actual").value(0.61));
    }

    @Test
    @DisplayName("모르는 종목이면 404")
    void estimates_404() throws Exception {
        when(queryService.estimates("ZZZ", 1L)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/v1/internal/assistant/stocks/ZZZ/estimates").param("as_of_epoch", "1"))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("용어 사전은 공개 엔드포인트와 같은 본문")
    void glossary_200() throws Exception {
        when(glossaryService.glossary()).thenReturn(new Glossary(1, List.of(
                new Glossary.Term("comp sales", List.of("comps"), "기존점 매출", null, null, "retail"))));

        mockMvc.perform(get("/api/v1/internal/assistant/glossary"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.terms[0].term").value("comp sales"));
    }
}
