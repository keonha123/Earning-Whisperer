package com.earningwhisperer.presentation.auth;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * Body fallback 용 Refresh Token 요청.
 * Cookie / X-Refresh-Token 헤더를 사용하지 못하는 클라이언트 대비.
 */
@Getter
@NoArgsConstructor
public class RefreshRequest {

    @JsonProperty("refresh_token")
    private String refreshToken;
}
