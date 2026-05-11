package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Async;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Market Screen 시가총액 표시를 위해 S&P 500 상위 50개 종목 StockMeta 일괄 동기화.
 * - 앱 시작 시 1회 (Async)
 * - 매일 UTC 22:00 장 마감 후 1회
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
public class Sp500TopMetaSyncScheduler {

    private static final int TOP_N = 50;

    private final StockMetaSyncService stockMetaSyncService;
    private final StockRepository stockRepository;

    @Async
    @EventListener(ApplicationReadyEvent.class)
    public void syncOnStartup() {
        sync("startup");
    }

    @Scheduled(cron = "0 0 22 * * *", zone = "UTC")
    public void syncDaily() {
        sync("daily");
    }

    private void sync(String trigger) {
        List<String> tickers = stockRepository.findAllActiveWithMetaSorted()
                .stream()
                .map(row -> ((Stock) row[0]).getTicker())
                .limit(TOP_N)
                .toList();

        if (tickers.isEmpty()) return;

        log.info("[Sp500TopMetaSync][{}] 상위 {}개 종목 StockMeta 동기화 시작", trigger, tickers.size());
        int success = 0, failed = 0;

        for (String ticker : tickers) {
            try {
                Stock stock = stockRepository.findByTicker(ticker).orElse(null);
                if (stock == null || stock.getId() == null) { failed++; continue; }
                if (stockMetaSyncService.syncTicker(stock.getId(), ticker, SyncPriority.LOW)) {
                    success++;
                } else {
                    failed++;
                }
            } catch (Exception e) {
                failed++;
                log.warn("[Sp500TopMetaSync] {} 실패: {}", ticker, e.getMessage());
            }
        }

        log.info("[Sp500TopMetaSync][{}] 완료 — success={} failed={}", trigger, success, failed);
    }
}
