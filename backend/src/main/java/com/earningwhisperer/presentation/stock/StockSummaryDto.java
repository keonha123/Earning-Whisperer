package com.earningwhisperer.presentation.stock;

import com.fasterxml.jackson.annotation.JsonProperty;

public record StockSummaryDto(
        String ticker,
        @JsonProperty("companyName") String companyName,
        String sector,
        @JsonProperty("marketCapUsd") Double marketCapUsd,
        @JsonProperty("currentPrice") Double currentPrice,
        @JsonProperty("changePercent") Double changePercent
) {}
