package com.earningwhisperer.global.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 인증 실패는 401 이어야 한다.
 *
 * <p>Spring Security 기본값({@code Http403ForbiddenEntryPoint})은 인증이 아예 없는
 * 요청에도 403 을 돌려준다. 그러면 클라이언트가 "토큰이 만료됐다" 와 "권한이 없다" 를
 * 구분할 수 없다. 터미널과 웹 프론트 모두 <b>401 에서만</b> 토큰을 갱신하고 재시도하도록
 * 만들어져 있어서, 403 이 오면 갱신 로직이 통째로 죽은 코드가 된다. 실제로 그 상태였고
 * 액세스 토큰이 만료되는 15분마다 로그인 화면으로 튕겼다.
 *
 * <p>대상 컨트롤러는 이 파일 안에서 정의한다. 실제 컨트롤러를 쓰면 그 컨트롤러의 생성자
 * 의존성이 늘 때마다 이 테스트가 무관한 이유로 깨진다.
 */
@WebMvcTest(controllers = SecurityConfigAuthEntryPointTest.ProbeController.class)
@Import({
        SecurityConfig.class,
        // 실물을 쓴다. mock 으로 두면 doFilter 가 아무것도 하지 않아 체인이 거기서 끊기고
        // 요청이 200 빈 응답으로 끝난다 — 시큐리티 규칙이 아예 적용되지 않는다.
        com.earningwhisperer.infrastructure.security.InternalSecretFilter.class,
})
@DisplayName("SecurityConfig 인증 실패 응답 규약")
class SecurityConfigAuthEntryPointTest {

    /** 인증이 필요한 임의 경로. anyRequest().authenticated() 규칙에 걸린다. */
    @RestController
    static class ProbeController {
        @GetMapping("/api/v1/probe")
        String probe() {
            return "ok";
        }
    }

    @Autowired MockMvc mockMvc;

    @MockBean com.earningwhisperer.infrastructure.security.JwtProvider jwtProvider;
    @MockBean com.earningwhisperer.infrastructure.security.UserDetailsServiceImpl userDetailsService;

    @Test
    @DisplayName("토큰 없이 보호된 엔드포인트 호출 — 403 이 아니라 401")
    void 토큰_없음_401() throws Exception {
        mockMvc.perform(get("/api/v1/probe"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("인증이 필요합니다."));
    }

    @Test
    @DisplayName("유효하지 않은 토큰도 401 — 만료와 위조를 구분해 알려주지 않는다")
    void 유효하지_않은_토큰_401() throws Exception {
        mockMvc.perform(get("/api/v1/probe").header(HttpHeaders.AUTHORIZATION, "Bearer not-a-jwt"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("인증이 필요합니다."));
    }

    @Test
    @DisplayName("본문이 UTF-8 JSON 이다 — 한글 메시지가 깨지지 않는다")
    void 응답_인코딩_규약() throws Exception {
        mockMvc.perform(get("/api/v1/probe"))
                .andExpect(content().contentTypeCompatibleWith("application/json"))
                .andExpect(content().encoding("UTF-8"))
                // 깨졌다면 '인증이' 가 물음표나 mojibake 로 바뀐다.
                .andExpect(content().string(org.hamcrest.Matchers.containsString("인증이 필요합니다.")));
    }

    @Test
    @DisplayName("401 에는 WWW-Authenticate 헤더가 붙는다 (RFC 9110)")
    void www_authenticate_헤더() throws Exception {
        mockMvc.perform(get("/api/v1/probe"))
                .andExpect(header().string(HttpHeaders.WWW_AUTHENTICATE, "Bearer realm=\"api\""));
    }
}
