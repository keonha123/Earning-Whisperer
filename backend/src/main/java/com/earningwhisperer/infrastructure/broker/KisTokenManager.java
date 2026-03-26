package com.earningwhisperer.infrastructure.broker;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.time.LocalDateTime;

/**
 * KIS Access Token 생명주기 관리.
 *
 * - 유효한 토큰이 있으면 캐시에서 즉시 반환 (만료 5분 전 선제 갱신)
 * - KIS는 동일 앱키로 토큰 중복 발급을 제한하므로 반드시 캐시 사용
 */
@Slf4j
@Component
public class KisTokenManager {

    private static final int REFRESH_BEFORE_MINUTES = 5;

    private final RestClient restClient;
    private final KisBrokerProperties properties;

    private volatile String cachedToken;
    private volatile LocalDateTime expiresAt;

    public KisTokenManager(RestClient.Builder builder, KisBrokerProperties properties) {
        this.restClient = builder.baseUrl(properties.getBaseUrl()).build();
        this.properties = properties;
    }

    /**
     * 유효한 access_token을 반환한다.
     * 만료 5분 전 이내이거나 캐시가 없으면 KIS에서 새 토큰을 발급받는다.
     */
    public String getAccessToken() {
        if (isTokenValid()) {
            return cachedToken;
        }
        return refresh();
    }

    private boolean isTokenValid() {
        return cachedToken != null
                && expiresAt != null
                && LocalDateTime.now().isBefore(expiresAt.minusMinutes(REFRESH_BEFORE_MINUTES));
    }

    private synchronized String refresh() {
        // double-checked locking: 이미 다른 스레드가 갱신했으면 재사용
        if (isTokenValid()) {
            return cachedToken;
        }

        log.info("[KisTokenManager] access_token 갱신 요청");

        KisTokenRequest request = new KisTokenRequest(
                "client_credentials",
                properties.getAppKey(),
                properties.getAppSecret()
        );

        KisTokenResponse response = restClient.post()
                .uri("/oauth2/tokenP")
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve()
                .body(KisTokenResponse.class);

        if (response == null || response.accessToken() == null) {
            throw new BrokerApiException("KIS 토큰 발급 실패: 응답이 null");
        }

        this.cachedToken = response.accessToken();
        this.expiresAt = LocalDateTime.now().plusSeconds(response.expiresIn());

        log.info("[KisTokenManager] access_token 갱신 완료, expiresAt={}", expiresAt);
        return cachedToken;
    }

    // --- KIS API 전용 내부 DTO ---

    private record KisTokenRequest(
            @JsonProperty("grant_type") String grantType,
            @JsonProperty("appkey") String appKey,
            @JsonProperty("appsecret") String appSecret
    ) {}

    private record KisTokenResponse(
            @JsonProperty("access_token") String accessToken,
            @JsonProperty("expires_in") long expiresIn
    ) {}
}
