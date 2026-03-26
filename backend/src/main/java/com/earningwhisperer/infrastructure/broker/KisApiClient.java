package com.earningwhisperer.infrastructure.broker;

import com.earningwhisperer.domain.signal.TradeAction;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * 한국투자증권(KIS) 모의투자 API 클라이언트.
 *
 * 해외주식 주문 API (모의투자):
 * - 매수 tr_id: VTTT1002U
 * - 매도 tr_id: VTTT1006U
 */
@Slf4j
@Component
public class KisApiClient implements BrokerApiClient {

    private static final String ORDER_PATH = "/uapi/overseas-stock/v1/trading/order";
    private static final String TR_ID_BUY  = "VTTT1002U";
    private static final String TR_ID_SELL = "VTTT1006U";

    // KIS 해외주식은 기본 NASDAQ으로 처리.
    // TODO: ticker별 거래소 코드 매핑 추가 (NASD, NYSE, AMEX 등)
    private static final String DEFAULT_EXCHANGE_CODE = "NASD";

    private final RestClient restClient;
    private final KisTokenManager tokenManager;
    private final KisBrokerProperties properties;

    public KisApiClient(RestClient.Builder builder, KisTokenManager tokenManager,
                        KisBrokerProperties properties) {
        this.restClient = builder.baseUrl(properties.getBaseUrl()).build();
        this.tokenManager = tokenManager;
        this.properties = properties;
    }

    @Override
    public BrokerOrderResponse placeOrder(BrokerOrderRequest request) {
        String token = tokenManager.getAccessToken();
        String trId = request.side() == TradeAction.BUY ? TR_ID_BUY : TR_ID_SELL;

        KisOrderBody body = new KisOrderBody(
                properties.getAccountNo(),
                properties.getAccountProductCode(),
                DEFAULT_EXCHANGE_CODE,
                request.ticker(),
                "01",                               // 시장가 주문
                String.valueOf(request.orderQty()),
                "0"                                 // 시장가 단가 = 0
        );

        log.info("[KisApiClient] 주문 요청 - ticker={} side={} qty={}",
                request.ticker(), request.side(), request.orderQty());

        KisOrderApiResponse response;
        try {
            response = restClient.post()
                    .uri(ORDER_PATH)
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("Authorization", "Bearer " + token)
                    .header("appkey", properties.getAppKey())
                    .header("appsecret", properties.getAppSecret())
                    .header("tr_id", trId)
                    .body(body)
                    .retrieve()
                    .body(KisOrderApiResponse.class);
        } catch (RestClientException e) {
            throw new BrokerApiException("KIS 주문 API 호출 실패: " + e.getMessage(), e);
        }

        if (response == null || response.output() == null || response.output().ordNo() == null) {
            throw new BrokerApiException("KIS 주문 응답 파싱 실패: output.ODNO 없음");
        }

        log.info("[KisApiClient] 주문 완료 - ordNo={}", response.output().ordNo());
        return new BrokerOrderResponse(response.output().ordNo(), request.orderQty());
    }

    // --- KIS API 전용 내부 DTO ---

    private record KisOrderBody(
            @JsonProperty("CANO")           String accountNo,
            @JsonProperty("ACNT_PRDT_CD")   String accountProductCode,
            @JsonProperty("OVRS_EXCG_CD")   String exchangeCode,
            @JsonProperty("PDNO")           String ticker,
            @JsonProperty("ORD_DVSN")       String orderDivision,
            @JsonProperty("ORD_QTY")        String orderQty,
            @JsonProperty("OVRS_ORD_UNPR")  String orderUnitPrice
    ) {}

    private record KisOrderApiResponse(
            @JsonProperty("rt_cd")  String returnCode,
            @JsonProperty("output") KisOrderOutput output
    ) {}

    private record KisOrderOutput(
            @JsonProperty("ODNO") String ordNo
    ) {}
}
