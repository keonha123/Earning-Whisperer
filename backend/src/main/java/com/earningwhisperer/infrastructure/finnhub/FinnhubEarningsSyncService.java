package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Optional;

/**
 * Finnhub `/calendar/earnings` 응답의 row 단위 어닝 일정 upsert 책임을 가진 서비스.
 *
 * <p>{@link com.earningwhisperer.infrastructure.finnhub.EarningsResultSyncService} 와 동일한 패턴 (PR #56,
 * Phase 2-B): row(= ticker × scheduledAt) 단위 {@code @Transactional} 격리 — 한 row 의 JPA 예외가 다른
 * row 의 commit 을 rollback-only 로 만들지 않도록 Service 빈을 별도로 분리한다.
 *
 * <p>스케줄러 단일 메서드에 {@code @Transactional} 을 걸고 per-row try/catch 로 진행하면 catch 후 다음
 * row 들이 정상 처리되는 듯 보이지만, commit 시점에 {@code UnexpectedRollbackException} 이 터지면서 모든
 * success 건도 함께 rollback 되는 silent data loss 가 발생할 수 있다. 본 서비스의 {@code @Transactional}
 * 은 scheduler 의 호출 경계마다 자체 트랜잭션을 시작하므로 한 row 의 실패는 자기 자신만 rollback 시키고
 * propagate 되어 스케줄러가 catch 한다.
 *
 * <p>FINNHUB_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Service
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class FinnhubEarningsSyncService {

    private final StockRepository stockRepository;
    private final EarningsCalendarRepository earningsCalendarRepository;

    /**
     * 한 row(= ticker × scheduledAt) 의 어닝 일정 upsert.
     *
     * <p>의미적 책임:
     * <ul>
     *     <li>Stock 미존재 (S&amp;P 500 외 종목) → {@link UpsertResult#SKIPPED}</li>
     *     <li>기존 row 갱신 → {@link UpsertResult#UPDATED}</li>
     *     <li>신규 row 삽입 → {@link UpsertResult#INSERTED}</li>
     *     <li>JPA / runtime 예외 → 자체 트랜잭션 rollback 후 propagate (스케줄러가 catch)</li>
     * </ul>
     *
     * <p>본 메서드는 {@code REQUIRED}({@code @Transactional} 기본값) — Scheduler 가 트랜잭션을 갖지
     * 않으므로 실질적으로 호출마다 새 트랜잭션이 시작된다. {@code REQUIRES_NEW} 가 아닌 사유는
     * PR #56 의 다른 sync service ({@link com.earningwhisperer.infrastructure.fmp.StockMetaSyncService}
     * 등) 와 일관성 — 격리는 Scheduler 가 트랜잭션을 갖지 않는 invariant 로 보장한다.
     *
     * @param ticker          외부 호출 키 (FinnhubCalendarRow.symbol)
     * @param scheduledAt     발표 예정 시각 (UTC)
     * @param confirmed       확정 여부
     * @param epsEstimate     EPS 컨센서스 (nullable)
     * @param revenueEstimate 매출 컨센서스 (nullable)
     * @return 처리 결과 분류 — 사이클 요약 카운트용
     */
    @Transactional
    public UpsertResult upsertRow(String ticker,
                                  Instant scheduledAt,
                                  boolean confirmed,
                                  String marketSession,
                                  BigDecimal epsEstimate,
                                  BigDecimal revenueEstimate) {
        Stock stock = stockRepository.findByTicker(ticker).orElse(null);
        if (stock == null) {
            return UpsertResult.SKIPPED;
        }

        Optional<EarningsCalendar> existing = earningsCalendarRepository
                .findByStockTickerAndScheduledAt(ticker, scheduledAt);

        if (existing.isPresent()) {
            existing.get().updateAll(scheduledAt, confirmed, marketSession, epsEstimate, revenueEstimate);
            return UpsertResult.UPDATED;
        }
        earningsCalendarRepository.save(EarningsCalendar.builder()
                .stock(stock)
                .scheduledAt(scheduledAt)
                .confirmed(confirmed)
                .marketSession(marketSession)
                .epsEstimate(epsEstimate)
                .revenueEstimate(revenueEstimate)
                .build());
        return UpsertResult.INSERTED;
    }

    /** 사이클 로깅용 row 처리 결과 분류. */
    public enum UpsertResult {
        /** 신규 EarningsCalendar 삽입 — 사이클 "new" 카운트에 반영. */
        INSERTED,
        /** 기존 row 갱신 — 신규는 아니지만 정상 처리. */
        UPDATED,
        /** Stock 미존재로 영속화 미진입 — 실패는 아니지만 success 도 아님. */
        SKIPPED
    }
}
