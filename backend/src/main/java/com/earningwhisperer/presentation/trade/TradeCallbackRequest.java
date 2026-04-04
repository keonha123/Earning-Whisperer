package com.earningwhisperer.presentation.trade;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * Contract 4 — Trading Terminal → 백엔드 체결 콜백 요청 DTO.
 *
 * Terminal이 KIS API로 주문 실행 후 결과를 POST /api/v1/trades/{tradeId}/callback 으로 전송.
 */
@Getter
@NoArgsConstructor
public class TradeCallbackRequest {

    @NotBlank
    private String status; // EXECUTED | FAILED

    @JsonProperty("broker_order_id")
    private String brokerOrderId;

    @JsonProperty("executed_price")
    private Double executedPrice;

    @JsonProperty("executed_qty")
    private Integer executedQty;

    @JsonProperty("error_message")
    private String errorMessage;
}
