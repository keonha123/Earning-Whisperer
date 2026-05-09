package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.infrastructure.websocket.StockPriceCache;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
public class FinnhubWebSocketManager {

    private static final int SYMBOLS_PER_KEY = 50;

    private final FinnhubProperties properties;
    private final StockPriceCache priceCache;
    private final StockRepository stockRepository;
    private final ObjectMapper objectMapper;

    @Async
    @EventListener(ApplicationReadyEvent.class)
    public void start() {
        List<String> activeKeys = properties.activeWsKeys();
        if (activeKeys.isEmpty()) {
            log.info("[FinnhubWS] ws-keys 미설정 — 실시간 가격 구독 비활성화");
            return;
        }

        List<String> topTickers = loadTopTickers(activeKeys.size() * SYMBOLS_PER_KEY);
        if (topTickers.isEmpty()) {
            log.warn("[FinnhubWS] 활성 종목 없음 — 구독 중단");
            return;
        }

        for (int i = 0; i < activeKeys.size(); i++) {
            int from = i * SYMBOLS_PER_KEY;
            if (from >= topTickers.size()) break;

            int to = Math.min(from + SYMBOLS_PER_KEY, topTickers.size());
            List<String> slice = topTickers.subList(from, to);
            String label = (i + 1) + "/" + activeKeys.size();

            Thread thread = new Thread(
                    new FinnhubWebSocketClient(activeKeys.get(i), slice, priceCache, objectMapper, label),
                    "finnhub-ws-" + (i + 1)
            );
            thread.setDaemon(true);
            thread.start();

            log.info("[FinnhubWS] 키 {} — {}~{}위 {}개 종목 구독 스레드 시작",
                    label, from + 1, to, slice.size());
        }
    }

    private List<String> loadTopTickers(int limit) {
        return stockRepository.findAllActiveWithMetaSorted()
                .stream()
                .map(row -> ((Stock) row[0]).getTicker())
                .limit(limit)
                .toList();
    }
}
