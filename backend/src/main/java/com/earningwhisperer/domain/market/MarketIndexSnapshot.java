package com.earningwhisperer.domain.market;

import com.earningwhisperer.infrastructure.redis.MarketIndicesMessage;

/**
 * 시장 지수 캐시/응답에 사용하는 단일 스냅샷.
 *
 * Contract 4.4 / 7.7 규격의 클라이언트 노출 6필드를 그대로 보유한다.
 * - symbol, price, change_percent, trend, format, timestamp
 *
 * 발행자 메타(schema_version, source, published_at)는 본 스냅샷에 포함하지 않는다.
 */
public record MarketIndexSnapshot(
        String symbol,
        double price,
        double changePercent,
        String trend,
        String format,
        long timestamp
) {

    /**
     * Redis 메시지로부터 trend / format을 가공해 스냅샷을 생성한다.
     * 호출자는 사전에 {@link MarketIndexFormat#isSupported(String)}로 5종 여부를 검증해야 한다.
     */
    public static MarketIndexSnapshot from(MarketIndicesMessage message) {
        return new MarketIndexSnapshot(
                message.getSymbol(),
                message.getPrice(),
                message.getChangePercent(),
                MarketIndexTrend.of(message.getChangePercent()),
                MarketIndexFormat.of(message.getSymbol()),
                message.getTimestamp()
        );
    }
}
