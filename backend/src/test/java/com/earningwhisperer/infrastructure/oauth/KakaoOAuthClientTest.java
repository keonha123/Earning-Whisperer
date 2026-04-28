package com.earningwhisperer.infrastructure.oauth;

import com.earningwhisperer.domain.user.OAuthExchangeException;
import com.earningwhisperer.domain.user.OAuthProvider;
import com.earningwhisperer.domain.user.OAuthUserProfile;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withBadRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

@DisplayName("KakaoOAuthClient 단위 테스트")
class KakaoOAuthClientTest {

    private static final String REDIRECT_URI = "http://localhost:3000/auth/callback";
    private static final String TOKEN_URL = "https://kauth.kakao.com/oauth/token";
    private static final String USERINFO_URL = "https://kapi.kakao.com/v2/user/me";

    private RestClient.Builder builder;
    private MockRestServiceServer server;
    private KakaoOAuthClient client;

    @BeforeEach
    void setUp() {
        builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        RestClient restClient = builder.build();
        client = new KakaoOAuthClient(
                "test-client-id",
                "test-client-secret",
                List.of(REDIRECT_URI),
                restClient);
    }

    private void expectTokenExchange() {
        server.expect(requestTo(TOKEN_URL))
                .andExpect(method(org.springframework.http.HttpMethod.POST))
                .andRespond(withSuccess(
                        "{\"access_token\":\"kakao-at\",\"token_type\":\"bearer\"}",
                        MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("이메일이 있는 정상 응답 → 매핑된 OAuthUserProfile 반환")
    void exchange_정상_이메일_있음() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andExpect(method(org.springframework.http.HttpMethod.GET))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 1234567890,"
                                + "\"kakao_account\": {"
                                + "  \"email\": \"kakao-user@example.com\","
                                + "  \"is_email_verified\": true,"
                                + "  \"profile\": { \"nickname\": \"카카오짱\" }"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.providerId()).isEqualTo("1234567890");
        assertThat(profile.email()).isEqualTo("kakao-user@example.com");
        assertThat(profile.nickname()).isEqualTo("카카오짱");
        assertThat(profile.provider()).isEqualTo(OAuthProvider.KAKAO);
        server.verify();
    }

    @Test
    @DisplayName("이메일이 없는 응답 → sentinel 이메일 + 닉네임 폴백")
    void exchange_이메일_없음_sentinel_생성() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 9876543210,"
                                + "\"kakao_account\": {"
                                + "  \"profile\": {}"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.providerId()).isEqualTo("9876543210");
        assertThat(profile.email()).isEqualTo("kakao_9876543210@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("카카오사용자_3210");
        assertThat(profile.provider()).isEqualTo(OAuthProvider.KAKAO);
        server.verify();
    }

    @Test
    @DisplayName("이메일 없음 + profile.nickname 있음 → nickname 우선 사용")
    void exchange_이메일_없음_닉네임_있음() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 5555,"
                                + "\"kakao_account\": {"
                                + "  \"profile\": { \"nickname\": \"실제닉네임\" }"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.email()).isEqualTo("kakao_5555@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("실제닉네임");
    }

    @Test
    @DisplayName("이메일은 있지만 미인증(is_email_verified=false) → 예외")
    void exchange_이메일_미인증_예외() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 111,"
                                + "\"kakao_account\": {"
                                + "  \"email\": \"unverified@example.com\","
                                + "  \"is_email_verified\": false,"
                                + "  \"profile\": { \"nickname\": \"미인증\" }"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.exchange("auth-code", REDIRECT_URI))
                .isInstanceOf(OAuthExchangeException.class)
                .hasMessageContaining("인증되지 않았습니다");
    }

    @Test
    @DisplayName("이메일 없을 때는 is_email_verified 검증을 건너뛴다")
    void exchange_이메일_없음_verified_검증_스킵() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 222,"
                                + "\"kakao_account\": {"
                                + "  \"is_email_verified\": false,"
                                + "  \"profile\": { \"nickname\": \"닉네임만\" }"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.email()).isEqualTo("kakao_222@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("닉네임만");
    }

    @Test
    @DisplayName("providerId가 4자리 미만이면 닉네임 suffix는 전체 providerId")
    void exchange_providerId_짧을때_suffix_전체() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 42,"
                                + "\"kakao_account\": {"
                                + "  \"profile\": {}"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.email()).isEqualTo("kakao_42@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("카카오사용자_42");
    }

    @Test
    @DisplayName("허용되지 않은 redirect_uri → OAuthExchangeException")
    void exchange_허용되지_않은_redirect_uri() {
        assertThatThrownBy(() -> client.exchange("code", "https://evil.example.com/cb"))
                .isInstanceOf(OAuthExchangeException.class)
                .hasMessageContaining("허용되지 않은");
    }

    @Test
    @DisplayName("email이 빈 문자열(\"\") → sentinel 이메일 생성")
    void exchange_email_빈문자열_sentinel_생성() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 7777,"
                                + "\"kakao_account\": {"
                                + "  \"email\": \"\","
                                + "  \"profile\": { \"nickname\": \"빈이메일\" }"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.email()).isEqualTo("kakao_7777@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("빈이메일");
    }

    @Test
    @DisplayName("email이 공백만(\"   \") → sentinel 이메일 생성")
    void exchange_email_공백만_sentinel_생성() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 8888,"
                                + "\"kakao_account\": {"
                                + "  \"email\": \"   \","
                                + "  \"profile\": { \"nickname\": \"공백이메일\" }"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.email()).isEqualTo("kakao_8888@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("공백이메일");
    }

    @Test
    @DisplayName("kakao_account 자체가 응답에 없음 → OAuthExchangeException")
    void exchange_kakao_account_누락_예외() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{ \"id\": 1111 }",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.exchange("auth-code", REDIRECT_URI))
                .isInstanceOf(OAuthExchangeException.class)
                .hasMessageContaining("Kakao 계정 정보");
    }

    @Test
    @DisplayName("is_email_verified 키 누락 + email 있음 → OAuthExchangeException (회귀 보장)")
    void exchange_is_email_verified_키_누락_예외() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 2222,"
                                + "\"kakao_account\": {"
                                + "  \"email\": \"someone@example.com\","
                                + "  \"profile\": { \"nickname\": \"검증안됨\" }"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.exchange("auth-code", REDIRECT_URI))
                .isInstanceOf(OAuthExchangeException.class)
                .hasMessageContaining("인증되지 않았습니다");
    }

    @Test
    @DisplayName("kakao_account.profile 자체 누락 + 이메일 없음 → 닉네임 폴백")
    void exchange_profile_자체_누락_닉네임_폴백() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 3333,"
                                + "\"kakao_account\": {}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.email()).isEqualTo("kakao_3333@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("카카오사용자_3333");
    }

    @Test
    @DisplayName("providerId 정확히 4자리 → suffix 4자리 그대로 (boundary)")
    void exchange_providerId_정확히_4자리_boundary() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andRespond(withSuccess(
                        "{"
                                + "\"id\": 4242,"
                                + "\"kakao_account\": {"
                                + "  \"profile\": {}"
                                + "}"
                                + "}",
                        MediaType.APPLICATION_JSON));

        OAuthUserProfile profile = client.exchange("auth-code", REDIRECT_URI);

        assertThat(profile.email()).isEqualTo("kakao_4242@earningwhisperer.local");
        assertThat(profile.nickname()).isEqualTo("카카오사용자_4242");
    }

    @Test
    @DisplayName("토큰 교환 단계에서 5xx → OAuthExchangeException으로 wrap")
    void exchange_토큰_단계_5xx_예외_wrap() {
        server.expect(requestTo(TOKEN_URL))
                .andExpect(method(org.springframework.http.HttpMethod.POST))
                .andRespond(withServerError());

        assertThatThrownBy(() -> client.exchange("auth-code", REDIRECT_URI))
                .isInstanceOf(OAuthExchangeException.class)
                .hasMessageContaining("카카오 토큰 교환 실패");
    }

    @Test
    @DisplayName("사용자 정보 조회 단계에서 4xx → OAuthExchangeException으로 wrap")
    void exchange_userinfo_단계_4xx_예외_wrap() {
        expectTokenExchange();
        server.expect(requestTo(USERINFO_URL))
                .andExpect(method(org.springframework.http.HttpMethod.GET))
                .andRespond(withBadRequest());

        assertThatThrownBy(() -> client.exchange("auth-code", REDIRECT_URI))
                .isInstanceOf(OAuthExchangeException.class)
                .hasMessageContaining("카카오 사용자 정보 조회 실패");
    }
}
