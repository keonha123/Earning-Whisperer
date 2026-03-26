package com.earningwhisperer.infrastructure.broker;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

@DisplayName("KisTokenManager 단위 테스트")
class KisTokenManagerTest {

    private MockRestServiceServer mockServer;
    private KisTokenManager tokenManager;

    @BeforeEach
    void setUp() {
        KisBrokerProperties properties = new KisBrokerProperties();
        properties.setBaseUrl("https://test.kis.com");
        properties.setAppKey("testKey");
        properties.setAppSecret("testSecret");

        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        tokenManager = new KisTokenManager(builder, properties);
    }

    @Test
    @DisplayName("토큰이 없으면 KIS API를 호출하여 새 토큰을 발급받는다")
    void 토큰_없으면_신규_발급() {
        // Arrange
        mockServer.expect(requestTo("https://test.kis.com/oauth2/tokenP"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess("""
                        {"access_token":"test-token-123","expires_in":86400}
                        """, MediaType.APPLICATION_JSON));

        // Act
        String token = tokenManager.getAccessToken();

        // Assert
        assertThat(token).isEqualTo("test-token-123");
        mockServer.verify();
    }

    @Test
    @DisplayName("유효한 토큰이 캐시에 있으면 API를 재호출하지 않는다")
    void 유효한_토큰은_캐시에서_반환() {
        // Arrange — 최초 1회만 서버 응답 설정
        mockServer.expect(requestTo("https://test.kis.com/oauth2/tokenP"))
                .andRespond(withSuccess("""
                        {"access_token":"cached-token","expires_in":86400}
                        """, MediaType.APPLICATION_JSON));

        // Act — 두 번 호출
        String first = tokenManager.getAccessToken();
        String second = tokenManager.getAccessToken();

        // Assert — 동일 토큰, API 1회만 호출
        assertThat(first).isEqualTo("cached-token");
        assertThat(second).isEqualTo("cached-token");
        mockServer.verify(); // 정확히 1번 호출됐는지 검증
    }

    @Test
    @DisplayName("KIS API가 null 응답을 반환하면 BrokerApiException이 발생한다")
    void API_오류시_BrokerApiException_발생() {
        // Arrange
        mockServer.expect(requestTo("https://test.kis.com/oauth2/tokenP"))
                .andRespond(withSuccess("{}", MediaType.APPLICATION_JSON));

        // Act & Assert
        assertThatThrownBy(() -> tokenManager.getAccessToken())
                .isInstanceOf(BrokerApiException.class)
                .hasMessageContaining("토큰 발급 실패");
    }
}
