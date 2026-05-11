package com.earningwhisperer.presentation.market;

import com.earningwhisperer.domain.market.MarketIndexSnapshot;
import com.earningwhisperer.domain.market.MarketIndicesCache;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * MarketIndicesController 슬라이스 테스트.
 *
 * - 인증 불필요(SecurityConfig permitAll) 검증
 * - 캐시 비어 있으면 200 + []
 * - 5종 캐시된 경우 6필드(snake_case) 응답
 */
@WebMvcTest(MarketIndicesController.class)
@Import({
        com.earningwhisperer.global.config.SecurityConfig.class,
        com.earningwhisperer.global.exception.GlobalExceptionHandler.class
})
@DisplayName("MarketIndicesController 슬라이스 테스트")
class MarketIndicesControllerTest {

    @Autowired MockMvc mockMvc;

    @MockBean MarketIndicesCache cache;
    @MockBean com.earningwhisperer.infrastructure.security.JwtProvider jwtProvider;
    @MockBean com.earningwhisperer.infrastructure.security.UserDetailsServiceImpl userDetailsService;

    @Test
    @DisplayName("캐시가 비어 있으면 200 OK 와 함께 빈 배열을 반환한다")
    void 빈_캐시_빈_배열_반환() throws Exception {
        when(cache.getAll()).thenReturn(List.of());

        mockMvc.perform(get("/api/v1/market/indices"))
                .andExpect(status().isOk())
                .andExpect(content().json("[]"));
    }

    @Test
    @DisplayName("5종 캐시된 경우 6필드를 snake_case 로 응답한다")
    void 캐시된_5종_응답_검증() throws Exception {
        when(cache.getAll()).thenReturn(List.of(
                new MarketIndexSnapshot("10Y", 4.35, -0.10, "down", "percent", 1745000000L),
                new MarketIndexSnapshot("DXY", 104.20, 0.30, "up", "index", 1745000001L),
                new MarketIndexSnapshot("NDX", 18500.50, 0.02, "neutral", "index", 1745000002L),
                new MarketIndexSnapshot("SPX", 5300.25, 0.85, "up", "index", 1745000003L),
                new MarketIndexSnapshot("VIX", 14.50, -1.20, "down", "index", 1745000004L)
        ));

        mockMvc.perform(get("/api/v1/market/indices"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(5))
                .andExpect(jsonPath("$[0].symbol").value("10Y"))
                .andExpect(jsonPath("$[0].price").value(4.35))
                .andExpect(jsonPath("$[0].change_percent").value(-0.10))
                .andExpect(jsonPath("$[0].trend").value("down"))
                .andExpect(jsonPath("$[0].format").value("percent"))
                .andExpect(jsonPath("$[0].timestamp").value(1745000000L))
                .andExpect(jsonPath("$[3].symbol").value("SPX"))
                .andExpect(jsonPath("$[3].format").value("index"))
                .andExpect(jsonPath("$[3].trend").value("up"))
                // 발행자 메타 누출 금지 (Contract 4.4 / 7.7)
                .andExpect(jsonPath("$[0].source").doesNotExist())
                .andExpect(jsonPath("$[0].schema_version").doesNotExist())
                .andExpect(jsonPath("$[0].published_at").doesNotExist());
    }

    @Test
    @DisplayName("인증 없이 접근 가능하다 (permitAll)")
    void 인증_불필요_접근() throws Exception {
        when(cache.getAll()).thenReturn(List.of());

        mockMvc.perform(get("/api/v1/market/indices"))
                .andExpect(status().isOk());
    }
}
