package com.earningwhisperer.presentation.glossary;

import com.earningwhisperer.infrastructure.glossary.Glossary;
import com.earningwhisperer.infrastructure.glossary.GlossaryService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * GlossaryController 슬라이스 테스트.
 *
 * 응답 필드 이름(snake_case)과 선택 필드 생략만 본다. 인증은 SecurityConfig 기본 규칙을 따른다.
 */
@WebMvcTest(controllers = GlossaryController.class,
        excludeAutoConfiguration = org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration.class)
@AutoConfigureMockMvc(addFilters = false)
@DisplayName("GlossaryController 슬라이스 테스트")
class GlossaryControllerTest {

    @Autowired MockMvc mockMvc;
    @MockBean GlossaryService service;

    @Test
    @DisplayName("정의가 있는 용어는 definition_ko · why_ko 를, 없는 용어는 필드를 생략해 내려준다")
    void glossary_200() throws Exception {
        when(service.glossary()).thenReturn(new Glossary(1, List.of(
                new Glossary.Term("comp sales", List.of("comps"), "기존점 매출",
                        "1년 이상 운영된 점포만 집계한 매출 증가율입니다.", "소매업의 핵심 지표입니다.", "retail"),
                new Glossary.Term("guidance", List.of(), "가이던스", null, null, "guidance"))));

        mockMvc.perform(get("/api/v1/glossary"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(1))
                .andExpect(jsonPath("$.terms[0].term").value("comp sales"))
                .andExpect(jsonPath("$.terms[0].aliases[0]").value("comps"))
                .andExpect(jsonPath("$.terms[0].ko").value("기존점 매출"))
                .andExpect(jsonPath("$.terms[0].definition_ko").exists())
                .andExpect(jsonPath("$.terms[0].why_ko").exists())
                .andExpect(jsonPath("$.terms[1].definition_ko").doesNotExist())
                .andExpect(jsonPath("$.terms[1].why_ko").doesNotExist());
    }
}
