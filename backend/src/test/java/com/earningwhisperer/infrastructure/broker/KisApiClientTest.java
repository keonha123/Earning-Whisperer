package com.earningwhisperer.infrastructure.broker;

import com.earningwhisperer.domain.signal.TradeAction;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("KisApiClient 단위 테스트")
class KisApiClientTest {

    @Mock
    private KisTokenManager tokenManager;

    private MockRestServiceServer mockServer;
    private KisApiClient kisApiClient;
    private KisBrokerProperties properties;

    @BeforeEach
    void setUp() {
        properties = new KisBrokerProperties();
        properties.setBaseUrl("https://test.kis.com");
        properties.setAppKey("testKey");
        properties.setAppSecret("testSecret");
        properties.setAccountNo("12345678");
        properties.setAccountProductCode("01");

        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        kisApiClient = new KisApiClient(builder, tokenManager, properties);

        given(tokenManager.getAccessToken()).willReturn("mock-token");
    }

    @Test
    @DisplayName("BUY 주문 시 매수 tr_id(VTTT1002U)로 KIS API를 호출하고 brokerOrderId를 반환한다")
    void BUY_주문_성공() {
        // Arrange
        mockServer.expect(requestTo("https://test.kis.com/uapi/overseas-stock/v1/trading/order"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(header("tr_id", "VTTT1002U"))
                .andRespond(withSuccess("""
                        {"rt_cd":"0","output":{"ODNO":"0000123456"}}
                        """, MediaType.APPLICATION_JSON));

        // Act
        BrokerOrderResponse response = kisApiClient.placeOrder(
                new BrokerOrderRequest("NVDA", TradeAction.BUY, 1));

        // Assert
        assertThat(response.brokerOrderId()).isEqualTo("0000123456");
        assertThat(response.executedQty()).isEqualTo(1);
        mockServer.verify();
    }

    @Test
    @DisplayName("SELL 주문 시 매도 tr_id(VTTT1006U)로 KIS API를 호출한다")
    void SELL_주문_성공() {
        // Arrange
        mockServer.expect(requestTo("https://test.kis.com/uapi/overseas-stock/v1/trading/order"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(header("tr_id", "VTTT1006U"))
                .andRespond(withSuccess("""
                        {"rt_cd":"0","output":{"ODNO":"0000654321"}}
                        """, MediaType.APPLICATION_JSON));

        // Act
        BrokerOrderResponse response = kisApiClient.placeOrder(
                new BrokerOrderRequest("NVDA", TradeAction.SELL, 1));

        // Assert
        assertThat(response.brokerOrderId()).isEqualTo("0000654321");
        mockServer.verify();
    }

    @Test
    @DisplayName("KIS API가 ODNO 없이 응답하면 BrokerApiException이 발생한다")
    void ODNO_없는_응답시_예외발생() {
        // Arrange
        mockServer.expect(requestTo("https://test.kis.com/uapi/overseas-stock/v1/trading/order"))
                .andRespond(withSuccess("""
                        {"rt_cd":"0","output":{}}
                        """, MediaType.APPLICATION_JSON));

        // Act & Assert
        assertThatThrownBy(() -> kisApiClient.placeOrder(
                new BrokerOrderRequest("NVDA", TradeAction.BUY, 1)))
                .isInstanceOf(BrokerApiException.class)
                .hasMessageContaining("ODNO");
    }

    @Test
    @DisplayName("KIS API 호출 실패 시 BrokerApiException이 발생한다")
    void API_호출_실패시_예외발생() {
        // Arrange
        mockServer.expect(requestTo("https://test.kis.com/uapi/overseas-stock/v1/trading/order"))
                .andRespond(withServerError());

        // Act & Assert
        assertThatThrownBy(() -> kisApiClient.placeOrder(
                new BrokerOrderRequest("NVDA", TradeAction.BUY, 1)))
                .isInstanceOf(BrokerApiException.class);
    }
}
