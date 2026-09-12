package com.earningwhisperer.infrastructure.finnhub.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Finnhub {@code /quote} 응답.
 *
 * <p>필드명이 한 글자라 그대로 두면 읽을 수 없어 이름을 붙였다.
 * 심볼이 잘못되었거나 데이터가 없으면 모든 값이 0 으로 온다 — 예외가 아니라 0 이므로
 * 호출자가 {@link #hasPrice()} 로 걸러야 한다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record FinnhubQuote(
        /** 현재가 */
        @JsonProperty("c") double current,
        /** 전일 대비 변화량 */
        @JsonProperty("d") Double change,
        /** 전일 대비 변화율(%) */
        @JsonProperty("dp") Double changePercent,
        /** 전일 종가 */
        @JsonProperty("pc") double previousClose,
        /** 응답 시각 (epoch seconds) */
        @JsonProperty("t") long timestamp
) {
    public boolean hasPrice() {
        return current > 0;
    }

    /**
     * 변화율. 응답에 없으면 전일 종가로 직접 계산한다.
     * 장 시작 직후 등 일부 구간에서 dp 가 누락되는 것을 실측했다.
     */
    public double changePercentOrComputed() {
        if (changePercent != null) {
            return changePercent;
        }
        if (previousClose > 0) {
            return (current - previousClose) / previousClose * 100.0;
        }
        return 0.0;
    }
}
