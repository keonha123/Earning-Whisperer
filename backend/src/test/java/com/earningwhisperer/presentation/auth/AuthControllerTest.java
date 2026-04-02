package com.earningwhisperer.presentation.auth;

import com.earningwhisperer.domain.user.AuthService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(AuthController.class)
// @WebMvcTest는 @Service 빈을 스캔하지 않으므로 SecurityConfig를 명시적으로 임포트.
// 이로써 커스텀 SecurityConfig(permitAll 설정)가 기본 보안 설정을 대체한다.
@Import({
    com.earningwhisperer.global.config.SecurityConfig.class,
    com.earningwhisperer.global.exception.GlobalExceptionHandler.class
})
class AuthControllerTest {

    @Autowired MockMvc mockMvc;
    @Autowired ObjectMapper objectMapper;

    @MockBean AuthService authService;
    // SecurityConfig가 JwtProvider를 의존하므로 MockBean 필요
    @MockBean com.earningwhisperer.infrastructure.security.JwtProvider jwtProvider;
    @MockBean com.earningwhisperer.infrastructure.security.UserDetailsServiceImpl userDetailsService;

    @Test
    void signup_정상_요청_201_반환() throws Exception {
        // Arrange
        when(authService.signup(any(), any(), any())).thenReturn(1L);

        String body = objectMapper.writeValueAsString(new TestSignupRequest(
                "user@example.com", "password123", "테스터"));

        // Act & Assert
        mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        )
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value(1));
    }

    @Test
    void login_정상_요청_200_토큰_반환() throws Exception {
        // Arrange
        when(authService.login(any(), any())).thenReturn("jwt-token");

        String body = objectMapper.writeValueAsString(new TestLoginRequest(
                "user@example.com", "password123"));

        // Act & Assert
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        )
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accessToken").value("jwt-token"))
                .andExpect(jsonPath("$.tokenType").value("Bearer"));
    }

    @Test
    void login_잘못된_자격증명_400_반환() throws Exception {
        // Arrange
        when(authService.login(any(), any()))
                .thenThrow(new IllegalArgumentException("이메일 또는 비밀번호가 올바르지 않습니다."));

        String body = objectMapper.writeValueAsString(new TestLoginRequest(
                "user@example.com", "wrongpass"));

        // Act & Assert
        mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        )
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("이메일 또는 비밀번호가 올바르지 않습니다."));
    }

    @Test
    void signup_유효성_검사_실패_400_반환() throws Exception {
        // Arrange: 비밀번호 7자 (최소 8자 미만)
        String body = objectMapper.writeValueAsString(new TestSignupRequest(
                "user@example.com", "short12", "테스터"));

        // Act & Assert
        mockMvc.perform(post("/api/v1/auth/signup")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        )
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").exists());
    }

    // 테스트 전용 내부 레코드 (DTO 필드 직렬화용)
    record TestSignupRequest(String email, String password, String nickname) {}
    record TestLoginRequest(String email, String password) {}
}
