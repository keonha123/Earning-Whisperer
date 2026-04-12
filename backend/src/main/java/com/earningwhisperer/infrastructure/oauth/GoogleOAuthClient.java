package com.earningwhisperer.infrastructure.oauth;

import com.earningwhisperer.domain.user.OAuthExchangeException;
import com.earningwhisperer.domain.user.OAuthProvider;
import com.earningwhisperer.domain.user.OAuthUserProfile;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;

/**
 * Google OAuth 2.0 Authorization Code → 사용자 프로필 교환.
 *
 * 1. POST https://oauth2.googleapis.com/token (code → access_token)
 * 2. GET  https://www.googleapis.com/userinfo/v2/me (access_token → 프로필)
 */
@Slf4j
@Component
public class GoogleOAuthClient implements OAuthClient {

    private static final String TOKEN_URL = "https://oauth2.googleapis.com/token";
    private static final String USERINFO_URL = "https://www.googleapis.com/userinfo/v2/me";

    private final String clientId;
    private final String clientSecret;
    private final List<String> allowedRedirectUris;
    private final RestClient restClient;

    public GoogleOAuthClient(
            @Value("${oauth.google.client-id:}") String clientId,
            @Value("${oauth.google.client-secret:}") String clientSecret,
            @Value("${oauth.google.allowed-redirect-uris:http://localhost:3000/auth/callback}") List<String> allowedRedirectUris) {
        this.clientId = clientId;
        this.clientSecret = clientSecret;
        this.allowedRedirectUris = allowedRedirectUris;
        this.restClient = RestClient.create();
    }

    @Override
    public OAuthProvider provider() {
        return OAuthProvider.GOOGLE;
    }

    @Override
    @SuppressWarnings("unchecked")
    public OAuthUserProfile exchange(String code, String redirectUri) {
        // redirect_uri 서버 측 허용 목록 검증
        if (!allowedRedirectUris.contains(redirectUri)) {
            throw new OAuthExchangeException("허용되지 않은 redirect_uri: " + redirectUri);
        }

        // 1. code → access_token
        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("grant_type", "authorization_code");
        form.add("code", code);
        form.add("redirect_uri", redirectUri);
        form.add("client_id", clientId);
        form.add("client_secret", clientSecret);

        Map<String, Object> tokenResponse = restClient.post()
                .uri(TOKEN_URL)
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(form)
                .retrieve()
                .body(Map.class);

        if (tokenResponse == null || !tokenResponse.containsKey("access_token")) {
            throw new OAuthExchangeException("Google token exchange 실패");
        }

        String accessToken = (String) tokenResponse.get("access_token");

        // 2. access_token → 사용자 프로필
        Map<String, Object> userInfo = restClient.get()
                .uri(USERINFO_URL)
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .body(Map.class);

        if (userInfo == null || !userInfo.containsKey("id")) {
            throw new OAuthExchangeException("Google userinfo 조회 실패");
        }

        // email null 체크를 name 폴백보다 먼저 수행
        String email = (String) userInfo.get("email");
        if (email == null || email.isBlank()) {
            throw new OAuthExchangeException("Google 계정에 이메일이 없습니다");
        }

        // verified_email 체크 — 미인증 이메일로 계정 탈취 방지
        Boolean verifiedEmail = (Boolean) userInfo.get("verified_email");
        if (!Boolean.TRUE.equals(verifiedEmail)) {
            throw new OAuthExchangeException("Google 이메일이 인증되지 않았습니다");
        }

        String providerId = String.valueOf(userInfo.get("id"));
        String name = (String) userInfo.getOrDefault("name", email.split("@")[0]);

        return new OAuthUserProfile(providerId, email, name, OAuthProvider.GOOGLE);
    }
}
