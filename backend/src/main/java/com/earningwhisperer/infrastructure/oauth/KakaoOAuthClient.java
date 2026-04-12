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
 * Kakao OAuth 2.0 Authorization Code → 사용자 프로필 교환.
 *
 * 1. POST https://kauth.kakao.com/oauth/token (code → access_token)
 * 2. GET  https://kapi.kakao.com/v2/user/me (access_token → 프로필)
 */
@Slf4j
@Component
public class KakaoOAuthClient implements OAuthClient {

    private static final String TOKEN_URL = "https://kauth.kakao.com/oauth/token";
    private static final String USERINFO_URL = "https://kapi.kakao.com/v2/user/me";

    private final String clientId;
    private final String clientSecret;
    private final List<String> allowedRedirectUris;
    private final RestClient restClient;

    public KakaoOAuthClient(
            @Value("${oauth.kakao.client-id:}") String clientId,
            @Value("${oauth.kakao.client-secret:}") String clientSecret,
            @Value("${oauth.kakao.allowed-redirect-uris:http://localhost:3000/auth/callback}") List<String> allowedRedirectUris) {
        this.clientId = clientId;
        this.clientSecret = clientSecret;
        this.allowedRedirectUris = allowedRedirectUris;
        this.restClient = RestClient.create();
    }

    @Override
    public OAuthProvider provider() {
        return OAuthProvider.KAKAO;
    }

    @Override
    @SuppressWarnings("unchecked")
    public OAuthUserProfile exchange(String code, String redirectUri) {
        if (!allowedRedirectUris.contains(redirectUri)) {
            throw new OAuthExchangeException("허용되지 않은 redirect_uri: " + redirectUri);
        }

        // 1. code → access_token
        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("grant_type", "authorization_code");
        form.add("code", code);
        form.add("redirect_uri", redirectUri);
        form.add("client_id", clientId);
        if (clientSecret != null && !clientSecret.isBlank()) {
            form.add("client_secret", clientSecret);
        }

        Map<String, Object> tokenResponse = restClient.post()
                .uri(TOKEN_URL)
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(form)
                .retrieve()
                .body(Map.class);

        if (tokenResponse == null || !tokenResponse.containsKey("access_token")) {
            throw new OAuthExchangeException("Kakao token exchange 실패");
        }

        String accessToken = (String) tokenResponse.get("access_token");

        // 2. access_token → 사용자 프로필
        Map<String, Object> userInfo = restClient.get()
                .uri(USERINFO_URL)
                .header("Authorization", "Bearer " + accessToken)
                .header("Content-type", "application/x-www-form-urlencoded;charset=utf-8")
                .retrieve()
                .body(Map.class);

        if (userInfo == null || !userInfo.containsKey("id")) {
            throw new OAuthExchangeException("Kakao userinfo 조회 실패");
        }

        String providerId = String.valueOf(userInfo.get("id"));

        // kakao_account에서 이메일, 닉네임 추출
        Map<String, Object> kakaoAccount = (Map<String, Object>) userInfo.get("kakao_account");
        if (kakaoAccount == null) {
            throw new OAuthExchangeException("Kakao 계정 정보를 가져올 수 없습니다");
        }

        String email = (String) kakaoAccount.get("email");
        if (email == null || email.isBlank()) {
            throw new OAuthExchangeException("Kakao 계정에 이메일이 없습니다");
        }

        // 이메일 인증 여부 확인
        Boolean isEmailVerified = (Boolean) kakaoAccount.get("is_email_verified");
        if (!Boolean.TRUE.equals(isEmailVerified)) {
            throw new OAuthExchangeException("Kakao 이메일이 인증되지 않았습니다");
        }

        // 닉네임: profile.nickname → 이메일 앞부분 폴백
        String nickname = email.split("@")[0];
        Map<String, Object> profile = (Map<String, Object>) kakaoAccount.get("profile");
        if (profile != null && profile.get("nickname") != null) {
            nickname = (String) profile.get("nickname");
        }

        return new OAuthUserProfile(providerId, email, nickname, OAuthProvider.KAKAO);
    }
}
