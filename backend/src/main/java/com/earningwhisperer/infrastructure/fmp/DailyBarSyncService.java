package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.DailyBar;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.fmp.dto.FmpHistoricalBar;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

/**
 * 한 ticker 단위 30D 일봉 동기화의 영속화 책임을 가진 서비스.
 *
 * <p>{@link StockMetaSyncService} 와 동일하게 ticker 단위 {@code @Transactional} 격리:
 * 한 ticker 의 JPA 예외가 다른 ticker 의 commit 을 rollback-only 로 만들지 않는다.
 *
 * <p>FMP_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Service
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class DailyBarSyncService {

    private final FmpClient fmpClient;
    private final StockRepository stockRepository;
    private final DailyBarRepository dailyBarRepository;

    /**
     * 한 ticker 의 fetchHistorical + (stock_id, bar_date) upsert.
     *
     * @param stockId        영속화 대상 Stock 의 PK
     * @param ticker         외부 호출 키
     * @param historicalDays 가져올 일봉 일수
     * @param priority       FMP rate limiter 우선순위 (사용자 trigger=HIGH, 사전 동기화=LOW)
     * @return 정상 적재된 bar 수 (≥1 이면 success). 빈 응답 / Stock 미존재 시 0.
     */
    @Transactional
    public int syncTicker(Long stockId, String ticker, int historicalDays, SyncPriority priority) {
        List<FmpHistoricalBar> bars = fmpClient.fetchHistorical(
                ticker, historicalDays, priority.toFmp());

        if (bars.isEmpty()) {
            log.warn("[DailyBarSync] historical 조회 실패 ticker={}", ticker);
            return 0;
        }

        // 트랜잭션 분리 후에는 외부 트랜잭션이 없으므로 stockId 로 reattach.
        // WatchlistItem.getStock() 의 LAZY proxy 가 detached 상태로 전달되는 일관성 문제 방지.
        Stock attached = stockRepository.findById(stockId)
                .orElseGet(() -> stockRepository.findByTicker(ticker).orElse(null));
        if (attached == null) {
            log.warn("[DailyBarSync] Stock 미존재 ticker={} stockId={} — skip", ticker, stockId);
            return 0;
        }

        int processed = 0;
        for (FmpHistoricalBar bar : bars) {
            // FMP 응답에 date / close 가 누락되는 경우는 거의 없지만 방어적 가드.
            if (bar.date() == null || bar.close() == null) continue;

            Optional<DailyBar> existing = dailyBarRepository
                    .findByStock_IdAndBarDate(attached.getId(), bar.date());

            if (existing.isPresent()) {
                existing.get().updateClose(bar.close(), bar.volume());
            } else {
                dailyBarRepository.save(DailyBar.builder()
                        .stock(attached)
                        .barDate(bar.date())
                        .closePrice(bar.close())
                        .volume(bar.volume())
                        .build());
            }
            processed++;
        }
        return processed;
    }
}
