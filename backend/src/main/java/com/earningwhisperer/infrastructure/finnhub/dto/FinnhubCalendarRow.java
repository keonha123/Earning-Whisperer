package com.earningwhisperer.infrastructure.finnhub.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * Finnhub `/calendar/earnings` 응답의 earningsCalendar 배열 단일 항목.
 *
 * <p>모든 필드는 nullable — 컨센서스(epsEstimate / revenueEstimate) 가 없는 종목/시점이 다수.
 * 본 phase 에서는 symbol / date 만 영속화에 사용하지만, Phase 2 컨센서스 동기화에 대비해
 * estimate 필드도 함께 파싱해 둔다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record FinnhubCalendarRow(
        @JsonProperty("symbol") String symbol,

        @JsonProperty("date")
        @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd")
        LocalDate date,

        /** "bmo" (before market open) | "amc" (after market close) | "dmh" (during market hours). nullable. */
        @JsonProperty("hour") String hour,

        @JsonProperty("epsEstimate") BigDecimal epsEstimate,
        @JsonProperty("revenueEstimate") BigDecimal revenueEstimate
) {}
