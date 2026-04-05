package com.earningwhisperer.presentation.user;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * PUT /api/v1/users/settings — Trading Terminal 전용 설정 업데이트 요청 DTO.
 * emaThreshold는 포함하지 않으며, 기존 값을 유지한다.
 */
@Getter
@NoArgsConstructor
public class UserSettingsUpdateRequest {

    @NotNull
    @JsonProperty("trading_mode")
    private TradingMode tradingMode;

    @NotNull
    @DecimalMin("0.0") @DecimalMax("1.0")
    @JsonProperty("max_buy_ratio")
    private Double maxBuyRatio;

    @NotNull
    @DecimalMin("0.0") @DecimalMax("1.0")
    @JsonProperty("max_holding_ratio")
    private Double maxHoldingRatio;

    @NotNull
    @Min(1)
    @JsonProperty("cooldown_minutes")
    private Integer cooldownMinutes;
}
