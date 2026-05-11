package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.watchlist.WatchlistRepository;
import com.earningwhisperer.global.common.SyncPriority;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 관심종목(Watchlist) unique ticker 의 어닝 결과(EPS surprise) 백필 스케줄러.
 *
 * <p>매주 일요일 02:00 UTC — 분기 어닝 시즌 발표는 주로 평일에 몰리므로 일요일 새벽이면
 * 직전 주 발표분이 모두 영속화된다. Finnhub `/stock/earnings` 응답은 종목당 직전 4분기
 * (= 4 calls) 으로 제한되어 N=수십~수백 ticker 도 분당 60 안전선(0.5 req/s) 으로 처리 가능.
 *
 * <p>본 스케줄러는 {@code @Transactional} 을 가지지 않는다.
 * ticker 단위 트랜잭션은 {@link EarningsResultSyncService#syncTicker(Long, String, SyncPriority)} 가
 * 관리하며, 한 ticker 의 실패가 다른 ticker 의 commit 을 rollback 시키지 않도록 격리된다.
 *
 * <p>FINNHUB_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Component
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class EarningsResultSyncScheduler {

    /** 사이클 실패율이 임계 이상일 때 ERROR 로그로 승격 — 운영자 알람 트리거. */
    private static final double FAILURE_RATE_ERROR_THRESHOLD = 0.3;

    private final EarningsResultSyncService earningsResultSyncService;
    private final WatchlistRepository watchlistRepository;

    /** 매주 일요일 02:00 UTC — 관심종목 unique ticker 어닝 결과 백필. */
    @Scheduled(cron = "0 0 2 * * SUN", zone = "UTC")
    public void syncEarningsResults() {
        List<Stock> uniqueStocks = watchlistRepository.findDistinctStocks();

        if (uniqueStocks.isEmpty()) {
            log.info("[EarningsResultSync] 관심종목 비어있음 — 동기화 skip");
            return;
        }

        int total = uniqueStocks.size();
        int success = 0;
        int failed = 0;
        int upserted = 0;

        for (Stock stock : uniqueStocks) {
            if (stock == null || stock.getId() == null) {
                failed++;
                continue;
            }
            String ticker = stock.getTicker();
            try {
                int newRows = earningsResultSyncService.syncTicker(
                        stock.getId(), ticker, SyncPriority.LOW);
                upserted += newRows;
                success++;
            } catch (RuntimeException e) {
                failed++;
                log.warn("[EarningsResultSync] {} 동기화 실패", ticker, e);
            }
        }

        logCycleResult(total, success, failed, upserted);
    }

    private void logCycleResult(int total, int success, int failed, int upserted) {
        double failureRate = total == 0 ? 0.0 : (double) failed / total;
        if (failureRate >= FAILURE_RATE_ERROR_THRESHOLD) {
            log.error("[EarningsResultSync] 실패율 {}% (tickers={} success={} failed={} new={}) — 외부 API/쿼터 점검 필요",
                    (int) (failureRate * 100), total, success, failed, upserted);
        } else {
            log.info("[EarningsResultSync] 어닝 결과 동기화 완료 — tickers={} success={} failed={} new={}",
                    total, success, failed, upserted);
        }
    }
}
