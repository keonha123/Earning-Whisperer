package com.earningwhisperer.infrastructure.fmp.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * FMP `/v3/historical-price-full/{ticker}` 응답 wrapper.
 *
 * <p>응답 구조: <pre>{ "symbol": "AAPL", "historical": [ {...}, {...} ] }</pre>
 * FmpClient 는 historical 만 추출하여 List 로 반환하므로 본 record 는 내부 매핑용.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record FmpHistoricalResponse(
        @JsonProperty("symbol") String symbol,
        @JsonProperty("historical") List<FmpHistoricalBar> historical
) {}
