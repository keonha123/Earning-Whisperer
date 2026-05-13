package com.earningwhisperer.presentation.trade;

import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.trade.OrderType;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * Trading Terminal → 백엔드 수동 주문 기록 요청 DTO.
 *
 * Terminal 이 KIS API 로 수동 주문 실행 후 결과를 POST /api/v1/trades/manual 로 전송.
 * AI 시그널 없이 사용자가 직접 입력한 주문이므로 orderRatio/aiScore 는 기록하지 않는다.
 */
@Getter
@NoArgsConstructor
public class ManualTradeRequest {

    @NotBlank
    private String ticker;

    @NotNull
    private TradeAction side;

    @NotNull
    @JsonProperty("order_type")
    private OrderType orderType;

    @NotNull
    @Min(1)
    @JsonProperty("order_qty")
    private Integer orderQty;

    @NotNull
    @DecimalMin("0.0")
    private Double price;

    @NotNull
    @Min(0)
    @JsonProperty("executed_qty")
    private Integer executedQty;

    @JsonProperty("executed_price")
    private Double executedPrice;

    @Size(max = 50)
    @JsonProperty("broker_order_id")
    private String brokerOrderId;

    @NotBlank
    @Pattern(regexp = "EXECUTED|FAILED", message = "status 는 EXECUTED 또는 FAILED 여야 합니다.")
    private String status;

    @Size(max = 500)
    @JsonProperty("error_message")
    private String errorMessage;

    @AssertTrue(message = "EXECUTED 주문에는 broker_order_id 가 필수입니다.")
    public boolean isBrokerOrderIdPresentWhenExecuted() {
        if (!"EXECUTED".equals(status)) {
            return true;
        }
        return brokerOrderId != null && !brokerOrderId.isBlank();
    }
}
