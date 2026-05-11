package com.earningwhisperer.presentation.trade;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
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
    @Pattern(regexp = "EXECUTED|FAILED", message = "status 는 EXECUTED 또는 FAILED 여야 합니다.")
    private String status;

    @JsonProperty("broker_order_id")
    private String brokerOrderId;

    @JsonProperty("executed_price")
    private Double executedPrice;

    @JsonProperty("executed_qty")
    private Integer executedQty;

    @JsonProperty("error_message")
    private String errorMessage;

    /**
     * EXECUTED 콜백은 멱등 dedup 키로 brokerOrderId 가 반드시 필요하다.
     * UNIQUE(broker_order_id) 가 NULL 다중 허용이라 누락 시 dedup 무력화되므로 DTO 단계에서 거부.
     */
    @AssertTrue(message = "EXECUTED 콜백에는 broker_order_id 가 필수입니다.")
    public boolean isBrokerOrderIdPresentWhenExecuted() {
        if (!"EXECUTED".equals(status)) {
            return true;
        }
        return brokerOrderId != null && !brokerOrderId.isBlank();
    }
}
