package com.earningwhisperer.presentation.market;

import com.earningwhisperer.domain.market.MarketIndexSnapshot;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * GET /api/v1/market/indices 응답 단건.
 *
 * STOMP /topic/market/indices 페이로드와 동일한 6필드를 snake_case 로 직렬화한다.
 * (Contract 7.7 = Contract 4.4)
 */
public record MarketIndexResponse(
        String symbol,
        double price,
        @JsonProperty("change_percent") double changePercent,
        String trend,
        String format,
        long timestamp
) {

    public static MarketIndexResponse from(MarketIndexSnapshot snapshot) {
        return new MarketIndexResponse(
                snapshot.symbol(),
                snapshot.price(),
                snapshot.changePercent(),
                snapshot.trend(),
                snapshot.format(),
                snapshot.timestamp()
        );
    }
}
