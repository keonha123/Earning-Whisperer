package com.earningwhisperer.presentation.user;

import com.earningwhisperer.domain.portfolio.TradingMode;
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
    private TradingMode trading_mode;

    @NotNull
    @DecimalMin("0.0") @DecimalMax("1.0")
    private Double max_buy_ratio;

    @NotNull
    @DecimalMin("0.0") @DecimalMax("1.0")
    private Double max_holding_ratio;

    @NotNull
    @Min(1)
    private Integer cooldown_minutes;
}
