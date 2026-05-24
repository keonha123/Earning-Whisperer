package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.domain.stock.StockPriceSnapshot;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.TickerLatestClose;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

@Slf4j
@Component
@RequiredArgsConstructor
public class StockPriceCache {

    private final StockRepository stockRepository;
    private final DailyBarRepository dailyBarRepository;

    private final ConcurrentHashMap<String, StockPriceSnapshot> cache = new ConcurrentHashMap<>();
    private final Set<String> dirtyTickers = ConcurrentHashMap.newKeySet();

    @EventListener(ApplicationReadyEvent.class)
    public void initialize() {
        List<String> tickers = stockRepository.findByActiveTrue()
                .stream().map(s -> s.getTicker()).toList();
        if (tickers.isEmpty()) return;

        Map<String, Double> closeMap = dailyBarRepository.findLatestClosesByTickers(tickers)
                .stream()
                .collect(Collectors.toMap(
                        TickerLatestClose::ticker,
                        c -> c.close() != null ? c.close() : 0.0));

        long now = System.currentTimeMillis();
        for (String ticker : tickers) {
            double prev = closeMap.getOrDefault(ticker, 0.0);
            cache.put(ticker, new StockPriceSnapshot(ticker, prev, prev, 0.0, now));
        }
        log.info("[StockPriceCache] 초기화 완료 — {}개 종목 (DailyBar 있음: {}개)",
                tickers.size(), closeMap.size());
    }

    public void update(String ticker, double price) {
        StockPriceSnapshot existing = cache.get(ticker);
        if (existing == null) return;
        cache.put(ticker, existing.withPrice(price, System.currentTimeMillis()));
        dirtyTickers.add(ticker);
    }

    public Collection<StockPriceSnapshot> getAll() {
        return Collections.unmodifiableCollection(cache.values());
    }

    public Map<String, StockPriceSnapshot> getAllAsMap() {
        return Collections.unmodifiableMap(cache);
    }

    public List<StockPriceSnapshot> getDirtyAndClear() {
        if (dirtyTickers.isEmpty()) return List.of();
        Set<String> snapshot = new HashSet<>(dirtyTickers);
        dirtyTickers.removeAll(snapshot);
        return snapshot.stream()
                .map(cache::get)
                .filter(Objects::nonNull)
                .toList();
    }
}
