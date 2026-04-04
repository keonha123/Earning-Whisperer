package com.earningwhisperer.presentation.portfolio;

import com.earningwhisperer.domain.portfolio.TradingMode;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor
public class PortfolioSettingsUpdateRequest {

    @NotNull
    @DecimalMin("0.0") @DecimalMax("1.0")
    private Double buyAmountRatio;

    @NotNull
    @DecimalMin("0.0") @DecimalMax("1.0")
    private Double maxPositionRatio;

    @NotNull
    @Min(1)
    private Integer cooldownMinutes;

    @NotNull
    @DecimalMin("0.0") @DecimalMax("1.0")
    private Double emaThreshold;

    @NotNull
    private TradingMode tradingMode;
}
