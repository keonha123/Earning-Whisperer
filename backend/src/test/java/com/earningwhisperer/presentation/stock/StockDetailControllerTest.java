package com.earningwhisperer.presentation.stock;

import com.earningwhisperer.domain.stock.StockDetailResponse;
import com.earningwhisperer.domain.stock.StockDetailService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * {@link StockDetailController} 슬라이스 테스트.
 *
 * <p>{@link WithMockUser} 로 JWT 인증 우회 — Spring Security 통합(JwtAuthenticationFilter 실제
 * 검증) 은 본 phase 범위 외. 401 케이스는 컨트롤러 단위로 검증 어려워 skip 후 PR 본문에 명시.
 */
@WebMvcTest(StockDetailController.class)
@Import({
        com.earningwhisperer.global.config.SecurityConfig.class,
        com.earningwhisperer.global.exception.GlobalExceptionHandler.class
})
@DisplayName("StockDetailController 슬라이스 테스트")
class StockDetailControllerTest {

    @Autowired MockMvc mockMvc;

    @MockBean StockDetailService stockDetailService;
    @MockBean com.earningwhisperer.infrastructure.security.JwtProvider jwtProvider;
    @MockBean com.earningwhisperer.infrastructure.security.UserDetailsServiceImpl userDetailsService;

    @Test
    @DisplayName("정상 ticker → 200 + StockDetailResponse")
    @WithMockUser
    void 정상_응답() throws Exception {
        StockDetailResponse response = new StockDetailResponse(
                "AAPL", "Apple Inc.", "TECH", true,
                new StockDetailResponse.BasicInfo(
                        new BigDecimal("3000000000000"),
                        new BigDecimal("200.30"),
                        new BigDecimal("75.60"),
                        new BigDecimal("0.0049")
                ),
                List.of(new StockDetailResponse.DailyBarPoint(
                        LocalDate.parse("2026-04-30"),
                        new BigDecimal("180.00"),
                        1_000_000L)),
                new BigDecimal("180.00"),
                List.of(new StockDetailResponse.EarningsHistoryItem(
                        "Q1 FY26",
                        1745000000L,
                        new BigDecimal("1.20"),
                        new BigDecimal("1.35"),
                        new BigDecimal("12.50"),
                        new BigDecimal("3.45")
                )),
                new StockDetailResponse.NextEarning(
                        1755000000L,
                        new BigDecimal("1.40"),
                        new BigDecimal("100000000000"),
                        true
                ),
                false,
                null
        );
        when(stockDetailService.getDetail("AAPL")).thenReturn(Optional.of(response));

        mockMvc.perform(get("/api/v1/stocks/AAPL/detail"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ticker").value("AAPL"))
                .andExpect(jsonPath("$.companyName").value("Apple Inc."))
                .andExpect(jsonPath("$.sector").value("TECH"))
                .andExpect(jsonPath("$.active").value(true))
                .andExpect(jsonPath("$.basic.marketCapUsd").value(3000000000000L))
                .andExpect(jsonPath("$.basic.high52w").value(200.30))
                .andExpect(jsonPath("$.chart30d.length()").value(1))
                .andExpect(jsonPath("$.chart30d[0].date").value("2026-04-30"))
                .andExpect(jsonPath("$.chart30d[0].close").value(180.00))
                .andExpect(jsonPath("$.currentPrice").value(180.00))
                .andExpect(jsonPath("$.earningsHistory.length()").value(1))
                .andExpect(jsonPath("$.earningsHistory[0].fiscalPeriodLabel").value("Q1 FY26"))
                .andExpect(jsonPath("$.earningsHistory[0].announcedAt").value(1745000000L))
                .andExpect(jsonPath("$.nextEarning.scheduledAt").value(1755000000L))
                .andExpect(jsonPath("$.nextEarning.confirmed").value(true))
                .andExpect(jsonPath("$.partial").value(false))
                .andExpect(jsonPath("$.ai").doesNotExist());
    }

    @Test
    @DisplayName("partial=true 응답도 200 으로 그대로 전달")
    @WithMockUser
    void partial_응답_200() throws Exception {
        StockDetailResponse response = new StockDetailResponse(
                "XYZ", "XYZ", null, false,
                null,
                List.of(),
                null,
                List.of(),
                null,
                true,
                null
        );
        when(stockDetailService.getDetail("XYZ")).thenReturn(Optional.of(response));

        mockMvc.perform(get("/api/v1/stocks/XYZ/detail"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.partial").value(true))
                .andExpect(jsonPath("$.active").value(false))
                .andExpect(jsonPath("$.basic").doesNotExist())
                .andExpect(jsonPath("$.currentPrice").doesNotExist());
    }

    @Test
    @DisplayName("소문자 ticker → 400 + invalid ticker")
    @WithMockUser
    void 소문자_400() throws Exception {
        mockMvc.perform(get("/api/v1/stocks/aapl/detail"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("invalid ticker"));
    }

    @Test
    @DisplayName("11자 초과 ticker → 400")
    @WithMockUser
    void 너무_긴_ticker_400() throws Exception {
        mockMvc.perform(get("/api/v1/stocks/ABCDEFGHIJK/detail"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("invalid ticker"));
    }

    @Test
    @DisplayName("Service 가 empty Optional 반환 → 503")
    @WithMockUser
    void service_empty_503() throws Exception {
        when(stockDetailService.getDetail("FAIL")).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/v1/stocks/FAIL/detail"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error").value(
                        "stock detail unavailable — external sync failed"));
    }

    @Test
    @DisplayName("Service 가 RuntimeException → 500")
    @WithMockUser
    void service_throw_500() throws Exception {
        when(stockDetailService.getDetail("AAPL"))
                .thenThrow(new RuntimeException("boom"));

        mockMvc.perform(get("/api/v1/stocks/AAPL/detail"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error").value("internal error"));
    }

    @Test
    @DisplayName("Service IllegalArgumentException → 400 (안전망 분기)")
    @WithMockUser
    void service_iae_400() throws Exception {
        when(stockDetailService.getDetail(anyString()))
                .thenThrow(new IllegalArgumentException("invalid ticker: AAPL"));

        mockMvc.perform(get("/api/v1/stocks/AAPL/detail"))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("BRK.B (마침표) → 정규식 통과")
    @WithMockUser
    void dot_ticker_pass() throws Exception {
        StockDetailResponse response = new StockDetailResponse(
                "BRK.B", "Berkshire Hathaway", "FIN", true,
                null, List.of(), null, List.of(), null, true, null
        );
        when(stockDetailService.getDetail("BRK.B")).thenReturn(Optional.of(response));

        mockMvc.perform(get("/api/v1/stocks/BRK.B/detail"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ticker").value("BRK.B"));
    }
}
