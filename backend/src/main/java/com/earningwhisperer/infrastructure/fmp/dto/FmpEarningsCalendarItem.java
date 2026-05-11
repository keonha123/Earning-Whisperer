package com.earningwhisperer.infrastructure.fmp.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;

@JsonIgnoreProperties(ignoreUnknown = true)
public record FmpEarningsCalendarItem(
        @JsonProperty("symbol") String symbol,
        @JsonProperty("date") String date,
        @JsonProperty("epsEstimated") BigDecimal epsEstimated,
        @JsonProperty("revenueEstimated") BigDecimal revenueEstimated
) {}
