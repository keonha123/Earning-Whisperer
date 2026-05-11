package com.earningwhisperer.infrastructure.redis;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

/**
 * Data Pipeline 미가동 시 백엔드 단독으로 end-to-end 검증을 위한 mock 퍼블리셔.
 *
 * 활성화 조건 — application yml 에 다음을 명시한 경우에만 동작한다.
 *   market-indices:
 *     mock:
 *       enabled: true
 *
 * 기본값은 비활성. prod 에서는 절대 동작하지 않도록 명시적 옵트인 방식을 채택했다.
 * prod 프로파일에서는 Bean 등록 차단 (옵트인 프로퍼티 + 프로파일 가드 이중 보호).
 *
 * 매 60초마다 5종(SPX/NDX/VIX/DXY/10Y) 각각에 대해
 * Contract 6.3 규격 단건 페이로드를 Redis market-indices 채널에 publish 한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
@Profile("!prod")
@ConditionalOnProperty(prefix = "market-indices.mock", name = "enabled", havingValue = "true")
public class MarketIndicesMockPublisher {

    /** 5종 mock 시드. (symbol, basePrice). */
    private static final List<Map.Entry<String, Double>> SEEDS = List.of(
            Map.entry("SPX", 5300.0),
            Map.entry("NDX", 18500.0),
            Map.entry("VIX", 14.5),
            Map.entry("DXY", 104.2),
            Map.entry("10Y", 4.35)
    );

    private final RedisTemplate<String, String> redisTemplate;
    private final ObjectMapper objectMapper;

    @Scheduled(fixedRate = 60_000L)
    public void publishMockIndices() {
        long now = System.currentTimeMillis() / 1000L;
        for (Map.Entry<String, Double> seed : SEEDS) {
            try {
                String json = buildMockJson(seed.getKey(), seed.getValue(), now);
                redisTemplate.convertAndSend(RedisConfig.MARKET_INDICES_CHANNEL, json);
            } catch (JsonProcessingException e) {
                log.error("[MarketIndicesMock] 페이로드 직렬화 실패 - symbol={}", seed.getKey(), e);
            }
        }
        log.debug("[MarketIndicesMock] 5종 mock 페이로드 publish 완료 - timestamp={}", now);
    }

    private String buildMockJson(String symbol, double basePrice, long timestamp) throws JsonProcessingException {
        // 가격을 ±0.5% 범위에서 흔들고, 등락률은 -1.5% ~ +1.5% 범위로 무작위 생성.
        double jitter = ThreadLocalRandom.current().nextDouble(-0.005, 0.005);
        double price = round2(basePrice * (1.0 + jitter));
        double changePercent = round2(ThreadLocalRandom.current().nextDouble(-1.5, 1.5));

        Map<String, Object> payload = Map.of(
                "schema_version", "1.0",
                "source", "mock-publisher",
                "symbol", symbol,
                "price", price,
                "change_percent", changePercent,
                "timestamp", timestamp,
                "published_at", timestamp
        );
        return objectMapper.writeValueAsString(payload);
    }

    private static double round2(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
