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

        Map<String, Double> closeMap = latestCloses(tickers);

        long now = System.currentTimeMillis();
        for (String ticker : tickers) {
            double prev = closeMap.getOrDefault(ticker, 0.0);
            cache.put(ticker, new StockPriceSnapshot(ticker, prev, prev, 0.0, now));
        }
        log.info("[StockPriceCache] 초기화 완료 — {}개 종목 (DailyBar 있음: {}개)",
                tickers.size(), closeMap.size());
    }

    /**
     * 일봉이 새로 적재된 뒤 전일종가를 다시 읽어 온다.
     *
     * <p>전일종가는 기동 시 한 번만 채워졌기 때문에, 일봉을 동기화해도 앱을 재시작할
     * 때까지 옛 값이 남아 있었다. 그 값으로 변동률을 계산하면 화면에 없던 폭락이 뜬다 —
     * 실제로 WMT 가 4개월 전 종가(130.15)와 비교되어 -18.5% 로 표시됐다.
     *
     * <p>현재가는 유지한다. 실시간 시세를 일봉 종가로 덮어쓰면 안 된다.
     *
     * @return 값이 실제로 바뀐 종목 수.
     */
    public int refreshPreviousCloses() {
        if (cache.isEmpty()) return 0;
        Map<String, Double> closeMap = latestCloses(List.copyOf(cache.keySet()));
        long now = System.currentTimeMillis();
        int changed = 0;
        for (Map.Entry<String, Double> entry : closeMap.entrySet()) {
            double prev = entry.getValue();
            if (prev <= 0) continue;
            StockPriceSnapshot existing = cache.get(entry.getKey());
            if (existing == null || existing.previousClose() == prev) continue;
            cache.put(entry.getKey(), existing.withPreviousClose(prev, now));
            dirtyTickers.add(entry.getKey());
            changed++;
        }
        if (changed > 0) {
            log.info("[StockPriceCache] 전일종가 갱신 — {}개 종목", changed);
        }
        return changed;
    }

    private Map<String, Double> latestCloses(List<String> tickers) {
        return dailyBarRepository.findLatestClosesByTickers(tickers)
                .stream()
                .collect(Collectors.toMap(
                        TickerLatestClose::ticker,
                        c -> c.close() != null ? c.close() : 0.0));
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
