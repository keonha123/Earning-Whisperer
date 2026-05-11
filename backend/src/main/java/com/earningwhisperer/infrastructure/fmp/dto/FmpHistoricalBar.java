package com.earningwhisperer.infrastructure.fmp.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * FMP `/v3/historical-price-full/{ticker}` 응답의 historical 배열 단일 항목(일봉).
 *
 * <p>FMP 응답은 다수 필드(open, high, low, adjClose, ...)를 포함하지만 본 도메인에서는
 * date / close / volume 만 영속화하므로 나머지는 무시한다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record FmpHistoricalBar(
        @JsonProperty("date")
        @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd")
        LocalDate date,

        @JsonProperty("close") BigDecimal close,
        @JsonProperty("volume") Long volume
) {}
