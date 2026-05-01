package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.watchlist.WatchlistRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 관심종목(Watchlist) unique ticker 의 30일 일봉 사전 동기화.
 *
 * <p>매일 UTC 22:30 — Phase 2-C 의 가격반응 계산기에서 어닝 콜 시점 ±N일 일봉을 즉시 조회할 수 있도록
 * DB에 미리 적재한다. {@link StockMetaSyncScheduler} 와 30분 간격으로 분리해
 * FMP 호출이 동시에 몰리는 burst 를 회피한다.
 *
 * <p>일봉은 영구 보존(기존 row 삭제 X) — 신규 30일이 들어올 때마다 시계열이 누적된다.
 * 동일 (stock, bar_date) 쌍은 unique constraint 로 보호되며 코드 레벨 upsert 로 멱등성 유지.
 *
 * <p>본 스케줄러는 {@code @Transactional} 을 가지지 않는다.
 * ticker 단위 트랜잭션은 {@link DailyBarSyncService#syncTicker(Long, String, int)} 가 관리.
 *
 * <p>FMP_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Component
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class DailyBarSyncScheduler {

    /** 한 ticker 당 가져올 일봉 일수 — Phase 2-C 가격반응 ±10일 윈도 + 여유분. */
    private static final int HISTORICAL_DAYS = 30;

    /** 사이클 실패율이 임계 이상일 때 ERROR 로그로 승격 — 운영자 알람 트리거. */
    private static final double FAILURE_RATE_ERROR_THRESHOLD = 0.3;

    private final DailyBarSyncService dailyBarSyncService;
    private final WatchlistRepository watchlistRepository;

    /** 매일 UTC 22:30 — 관심종목 30D 일봉 적재. */
    @Scheduled(cron = "0 30 22 * * *", zone = "UTC")
    public void syncDailyBars() {
        List<Stock> uniqueStocks = watchlistRepository.findDistinctStocks();

        if (uniqueStocks.isEmpty()) {
            log.info("[DailyBarSync] 관심종목 비어있음 — 동기화 skip");
            return;
        }

        int total = uniqueStocks.size();
        int success = 0;
        int failed = 0;
        int barsUpserted = 0;

        for (Stock stock : uniqueStocks) {
            if (stock == null || stock.getId() == null) {
                failed++;
                continue;
            }
            String ticker = stock.getTicker();
            try {
                int barsForTicker = dailyBarSyncService.syncTicker(stock.getId(), ticker, HISTORICAL_DAYS);
                if (barsForTicker > 0) {
                    barsUpserted += barsForTicker;
                    success++;
                } else {
                    failed++;
                }
            } catch (RuntimeException e) {
                failed++;
                log.warn("[DailyBarSync] {} 동기화 실패", ticker, e);
            }
        }

        logCycleResult(total, success, failed, barsUpserted);
    }

    private void logCycleResult(int total, int success, int failed, int barsUpserted) {
        double failureRate = total == 0 ? 0.0 : (double) failed / total;
        if (failureRate >= FAILURE_RATE_ERROR_THRESHOLD) {
            log.error("[DailyBarSync] 실패율 {}% (tickers={} success={} failed={} bars={}) — 외부 API/쿼터 점검 필요",
                    (int) (failureRate * 100), total, success, failed, barsUpserted);
        } else {
            log.info("[DailyBarSync] 일봉 동기화 완료 — tickers={} success={} failed={} bars={}",
                    total, success, failed, barsUpserted);
        }
    }
}
