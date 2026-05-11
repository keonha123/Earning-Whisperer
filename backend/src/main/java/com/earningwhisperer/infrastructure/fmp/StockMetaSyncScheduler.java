package com.earningwhisperer.infrastructure.fmp;

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
 * 관심종목(Watchlist) unique ticker 의 종목 메타데이터(시가총액 / 52주 high·low / 배당수익률) 사전 동기화.
 *
 * <p>매일 UTC 22:00 에 실행 — NYSE 정규장 마감(21:00 UTC; DST 기준 EDT 17:00) 후 1시간 버퍼.
 * 마감 직후의 일중 변동/늦은 보고서 반영을 위해 다음 거래일 시작 전에 1회 갱신한다.
 *
 * <p>FMP 무료 티어(250 req/day) 보호를 위해 우선순위는 항상 LOW — 사용자 trigger 기반 호출
 * (HIGH 우선순위) 이 들어오면 RateLimiter 큐에서 먼저 drain 된다.
 *
 * <p>본 스케줄러는 {@code @Transactional} 을 가지지 않는다.
 * ticker 단위 트랜잭션은 {@link StockMetaSyncService#syncTicker(Long, String, SyncPriority)} 가 관리하며,
 * 한 ticker 의 실패가 다른 ticker 의 commit 을 rollback 시키지 않도록 격리된다.
 *
 * <p>FMP_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Component
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class StockMetaSyncScheduler {

    /** 사이클 실패율이 임계 이상일 때 ERROR 로그로 승격 — 운영자 알람 트리거. */
    private static final double FAILURE_RATE_ERROR_THRESHOLD = 0.3;

    private final StockMetaSyncService stockMetaSyncService;
    private final WatchlistRepository watchlistRepository;

    /**
     * 매일 UTC 22:00 — 관심종목 unique ticker 메타 갱신.
     *
     * <p>cron 시각 결정 사유:
     * <ul>
     *     <li>NYSE 마감: EDT 16:00 = UTC 20:00 (서머타임), EST 16:00 = UTC 21:00 (표준시)</li>
     *     <li>표준시 기준 마감 21:00 UTC + 1h 버퍼 → 22:00 UTC</li>
     *     <li>DailyBarSyncScheduler 와 30분 간격 → 22:00 (Meta) → 22:30 (Bar)</li>
     * </ul>
     */
    @Scheduled(cron = "0 0 22 * * *", zone = "UTC")
    public void syncStockMetas() {
        // unique stock 추출은 repository 측에서 DISTINCT 로 보장.
        // ticker 가 여러 사용자 watchlist 에 있어도 1건만 반환된다.
        List<Stock> uniqueStocks = watchlistRepository.findDistinctStocks();

        if (uniqueStocks.isEmpty()) {
            log.info("[StockMetaSync] 관심종목 비어있음 — 동기화 skip");
            return;
        }

        int total = uniqueStocks.size();
        int success = 0;
        int failed = 0;

        for (Stock stock : uniqueStocks) {
            if (stock == null || stock.getId() == null) {
                failed++;
                continue;
            }
            String ticker = stock.getTicker();
            try {
                if (stockMetaSyncService.syncTicker(stock.getId(), ticker, SyncPriority.LOW)) {
                    success++;
                } else {
                    failed++;
                }
            } catch (RuntimeException e) {
                // ticker 단위 트랜잭션이 자체 rollback 후 propagate 한 케이스.
                // stacktrace 포함 — NPE 등 message=null 케이스도 디버깅 가능.
                failed++;
                log.warn("[StockMetaSync] {} 동기화 실패", ticker, e);
            }
        }

        logCycleResult(total, success, failed);
    }

    private void logCycleResult(int total, int success, int failed) {
        double failureRate = total == 0 ? 0.0 : (double) failed / total;
        if (failureRate >= FAILURE_RATE_ERROR_THRESHOLD) {
            log.error("[StockMetaSync] 실패율 {}% (success={}, failed={}, total={}) — 외부 API/쿼터 점검 필요",
                    (int) (failureRate * 100), success, failed, total);
        } else {
            log.info("[StockMetaSync] 종목 메타 동기화 완료 — total={} success={} failed={}",
                    total, success, failed);
        }
    }
}
