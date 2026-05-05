package com.earningwhisperer.presentation.auth;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.RequiredArgsConstructor;

/**
 * 인증 응답 DTO. refresh_token 은 HttpOnly 쿠키로만 전달되며 본 응답 본문 / 응답 헤더에는
 * 절대 포함하지 않는다 (XSS 로 인한 7일 권한 탈취 방지).
 */
@Getter
@RequiredArgsConstructor
public class AuthResponse {

    @JsonProperty("access_token")
    private final String accessToken;

    @JsonProperty("token_type")
    private final String tokenType = "Bearer";
}
