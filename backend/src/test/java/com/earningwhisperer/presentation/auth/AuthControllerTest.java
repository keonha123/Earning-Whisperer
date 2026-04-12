package com.earningwhisperer.presentation.auth;

import com.earningwhisperer.domain.user.AuthService;
import com.earningwhisperer.domain.user.RefreshTokenService;
import com.earningwhisperer.domain.user.TokenPair;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(AuthController.class)
@Import({
    com.earningwhisperer.global.config.SecurityConfig.class,
    com.earningwhisperer.global.exception.GlobalExceptionHandler.class
})
@DisplayName("AuthController 통합 테스트")
class AuthControllerTest {

    @Autowired MockMvc mockMvc;
    @Autowired ObjectMapper objectMapper;

    @MockBean AuthService authService;
    @MockBean com.earningwhisperer.infrastructure.security.JwtProvider jwtProvider;
    @MockBean com.earningwhisperer.infrastructure.security.UserDetailsServiceImpl userDetailsService;

    @Test
    void signup_정상_요청_201_반환() throws Exception {
        when(authService.signup(any(), any(), any())).thenReturn(1L);

        String body = objectMapper.writeValueAsString(new TestSignupRequest(
                "user@example.com", "password123", "테스터"));

        mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value(1));
    }

    @Test
    @DisplayName("로그인 시 access_token, refresh_token, Set-Cookie 모두 반환된다")
    void login_정상_요청_200_토큰쌍_반환() throws Exception {
        when(authService.login(any(), any()))
                .thenReturn(new TokenPair("access-jwt", "refresh-uuid"));

        String body = objectMapper.writeValueAsString(new TestLoginRequest(
                "user@example.com", "password123"));

        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.access_token").value("access-jwt"))
                .andExpect(jsonPath("$.refresh_token").value("refresh-uuid"))
                .andExpect(jsonPath("$.token_type").value("Bearer"))
                .andExpect(header().exists("Set-Cookie"))
                .andExpect(header().exists("X-Refresh-Token"));
    }

    @Test
    void login_잘못된_자격증명_400_반환() throws Exception {
        when(authService.login(any(), any()))
                .thenThrow(new IllegalArgumentException("이메일 또는 비밀번호가 올바르지 않습니다."));

        String body = objectMapper.writeValueAsString(new TestLoginRequest(
                "user@example.com", "wrongpass"));

        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("이메일 또는 비밀번호가 올바르지 않습니다."));
    }

    @Test
    @DisplayName("Cookie로 refresh 요청 시 새 토큰 쌍이 반환된다")
    void refresh_Cookie로_갱신_성공() throws Exception {
        when(authService.refresh("old-rt"))
                .thenReturn(new TokenPair("new-access", "new-refresh"));

        mockMvc.perform(post("/api/v1/auth/refresh")
                        .cookie(new Cookie("refresh_token", "old-rt")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.access_token").value("new-access"))
                .andExpect(jsonPath("$.refresh_token").value("new-refresh"));
    }

    @Test
    @DisplayName("X-Refresh-Token 헤더로 refresh 요청 성공")
    void refresh_헤더로_갱신_성공() throws Exception {
        when(authService.refresh("old-rt"))
                .thenReturn(new TokenPair("new-access", "new-refresh"));

        mockMvc.perform(post("/api/v1/auth/refresh")
                        .header("X-Refresh-Token", "old-rt"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.access_token").value("new-access"));
    }

    @Test
    @DisplayName("RT 없이 refresh 요청 시 401")
    void refresh_RT없음_401() throws Exception {
        mockMvc.perform(post("/api/v1/auth/refresh"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("만료된 RT로 refresh 요청 시 401")
    void refresh_만료RT_401() throws Exception {
        when(authService.refresh("expired-rt"))
                .thenThrow(new RefreshTokenService.InvalidRefreshTokenException());

        mockMvc.perform(post("/api/v1/auth/refresh")
                        .header("X-Refresh-Token", "expired-rt"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("동시 갱신 경합 시 429")
    void refresh_동시갱신_429() throws Exception {
        when(authService.refresh("racing-rt"))
                .thenThrow(new RefreshTokenService.ConcurrentRefreshException());

        mockMvc.perform(post("/api/v1/auth/refresh")
                        .header("X-Refresh-Token", "racing-rt"))
                .andExpect(status().isTooManyRequests());
    }

    @Test
    @DisplayName("logout 시 204 + 쿠키 삭제")
    void logout_성공_204() throws Exception {
        mockMvc.perform(post("/api/v1/auth/logout")
                        .cookie(new Cookie("refresh_token", "some-rt")))
                .andExpect(status().isNoContent())
                .andExpect(header().exists("Set-Cookie"));

        verify(authService).logout("some-rt");
    }

    @Test
    void signup_유효성_검사_실패_400_반환() throws Exception {
        String body = objectMapper.writeValueAsString(new TestSignupRequest(
                "user@example.com", "short12", "테스터"));

        mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").exists());
    }

    record TestSignupRequest(String email, String password, String nickname) {}
    record TestLoginRequest(String email, String password) {}
}
