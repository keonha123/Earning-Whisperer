package com.earningwhisperer.infrastructure.finnhub.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Finnhub `/calendar/earnings` 응답 wrapper.
 *
 * <p>응답 구조: <pre>{ "earningsCalendar": [ {...}, {...} ] }</pre>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record FinnhubCalendarResponse(
        @JsonProperty("earningsCalendar") List<FinnhubCalendarRow> earningsCalendar
) {}
