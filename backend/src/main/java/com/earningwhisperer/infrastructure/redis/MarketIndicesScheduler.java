package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.infrastructure.finnhub.FinnhubClient;
import com.earningwhisperer.infrastructure.finnhub.FinnhubRateLimiter;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubQuote;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 시장 지수 스트립 데이터 수집기.
 *
 * <p>Finnhub {@code /quote} 로 대표 ETF 5종의 실시간 시세를 받아 Redis
 * {@code market-indices} 채널로 발행한다. 이후 경로(구독자 → 캐시 → STOMP fan-out)는
 * 기존 것을 그대로 쓴다.
 *
 * <p><b>왜 백엔드에서 직접 받는가.</b> 이 채널에는 원래 아무도 발행하지 않았다.
 * 백엔드는 구독만 하고 있었고, 화면에는 프론트엔드의 DEV 목업(SPX 5873.2 같은 고정값)이
 * 대신 떠 있었다. 지수 스트립은 다른 모듈에 의존할 이유가 없는 단순 시세 조회다.
 *
 * <p><b>왜 ETF 인가.</b> 원지수(SPX/NDX)는 유료 데이터다. SPY 를 10배 해서 SPX 라고
 * 표기하는 환산은 하지 않는다 — 실제 지수값과 다르고 화면에서는 거짓이 된다.
 * ETF 심볼을 그대로 노출한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class MarketIndicesScheduler {

    /** 표시 순서 그대로. 미국 시장 대표 ETF 5종. */
    private static final List<String> SYMBOLS = List.of("SPY", "QQQ", "DIA", "IWM", "VIXY");

    private static final String SOURCE = "finnhub-quote";

    private final FinnhubClient finnhubClient;
    private final RedisTemplate<String, String> redisTemplate;
    private final ObjectMapper objectMapper;

    @Async
    @EventListener(ApplicationReadyEvent.class)
    public void refreshOnStartup() {
        refresh("startup");
    }

    /**
     * 1분 주기. 5종 × 분당 1회 = Finnhub 무료 등급(분당 60회) 안에서 여유롭다.
     */
    @Scheduled(fixedRate = 60_000L, initialDelay = 60_000L)
    public void refreshPeriodically() {
        refresh("scheduled");
    }

    private void refresh(String trigger) {
        int published = 0;
        for (String symbol : SYMBOLS) {
            Optional<FinnhubQuote> quote = finnhubClient.fetchQuote(symbol, FinnhubRateLimiter.Priority.LOW);
            if (quote.isEmpty()) {
                continue;
            }
            if (publish(symbol, quote.get())) {
                published++;
            }
        }
        if (published == 0) {
            // 하나도 못 받으면 화면의 지수 스트립이 통째로 빈다. 조용히 넘기면
            // "장이 닫혀서 그런가" 로 오해하게 된다.
            log.warn("[MarketIndices] {} — 시세를 하나도 받지 못했습니다. Finnhub 키와 한도를 확인하세요.", trigger);
        } else {
            log.info("[MarketIndices] {} — {}/{}종 발행", trigger, published, SYMBOLS.size());
        }
    }

    private boolean publish(String symbol, FinnhubQuote quote) {
        // Contract 6.3 단건 페이로드. 필드 순서를 유지해야 로그를 눈으로 읽기 편하다.
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schema_version", "1.0");
        payload.put("source", SOURCE);
        payload.put("symbol", symbol);
        payload.put("price", round2(quote.current()));
        payload.put("change_percent", round2(quote.changePercentOrComputed()));
        long timestamp = quote.timestamp() > 0 ? quote.timestamp() : System.currentTimeMillis() / 1000L;
        payload.put("timestamp", timestamp);
        payload.put("published_at", System.currentTimeMillis() / 1000L);

        try {
            redisTemplate.convertAndSend(RedisConfig.MARKET_INDICES_CHANNEL, objectMapper.writeValueAsString(payload));
            return true;
        } catch (Exception e) {
            log.error("[MarketIndices] 발행 실패 - symbol={} error={}", symbol, e.getMessage(), e);
            return false;
        }
    }

    private static double round2(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
