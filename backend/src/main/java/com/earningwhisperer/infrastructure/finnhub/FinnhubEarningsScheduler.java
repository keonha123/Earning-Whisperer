package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubCalendarRow;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;

/**
 * Finnhub `/calendar/earnings` 호출 → {@code EarningsCalendar} upsert 스케줄러.
 *
 * <p>외부 API 호출 책임은 {@link FinnhubClient} 로, 분당 burst 제어는 {@link FinnhubRateLimiter} 로,
 * row 단위 영속화는 {@link FinnhubEarningsSyncService} 로 각각 분리되어 있다.
 *
 * <p>본 스케줄러는 {@code @Transactional} 을 가지지 않는다.
 * row 단위 트랜잭션은 {@link FinnhubEarningsSyncService#upsertRow(String, Instant, boolean,
 * java.math.BigDecimal, java.math.BigDecimal)} 가 관리하며, 한 row 의 실패가 다른 row 의 commit 을
 * rollback 시키지 않도록 격리된다 (PR #56, Phase 2-B 패턴).
 */
@Slf4j
@Component
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
@RequiredArgsConstructor
public class FinnhubEarningsScheduler {

    /** 사이클 실패율이 임계 이상일 때 ERROR 로그로 승격 — 운영자 알람 트리거. */
    private static final double FAILURE_RATE_ERROR_THRESHOLD = 0.3;

    private final FinnhubClient finnhubClient;
    private final FinnhubEarningsSyncService finnhubEarningsSyncService;

    /** 매일 오전 6시 UTC, 향후 30일 어닝 일정 갱신 */
    @Scheduled(cron = "0 0 6 * * *", zone = "UTC")
    public void syncEarningsCalendar() {
        LocalDate from = LocalDate.now(ZoneOffset.UTC);
        LocalDate to = from.plusDays(90);

        List<FinnhubCalendarRow> rows = finnhubClient.fetchCalendar(
                from, to, FinnhubRateLimiter.Priority.LOW);

        if (rows.isEmpty()) {
            log.info("[FinnhubEarningsScheduler] 어닝 일정 응답 없음 from={} to={}", from, to);
            return;
        }

        int total = 0;
        int inserted = 0;
        int updated = 0;
        int skipped = 0;
        int failed = 0;

        for (FinnhubCalendarRow row : rows) {
            if (row.date() == null || row.symbol() == null) continue;
            total++;
            Instant scheduledAt = row.date().atStartOfDay(ZoneOffset.UTC).toInstant();
            try {
                // estimate 는 Finnhub 응답에 필드 자체가 없을 수 있어 nullable. null 그대로 전달.
                FinnhubEarningsSyncService.UpsertResult result = finnhubEarningsSyncService.upsertRow(
                        row.symbol(),
                        scheduledAt,
                        true,
                        row.hour(),
                        row.epsEstimate(),
                        row.revenueEstimate());
                switch (result) {
                    case INSERTED -> inserted++;
                    case UPDATED -> updated++;
                    case SKIPPED -> skipped++;
                }
            } catch (RuntimeException e) {
                // row 단위 트랜잭션이 자체 rollback 후 propagate 한 케이스.
                // stacktrace 포함 — NPE 등 message=null 케이스도 디버깅 가능.
                failed++;
                log.warn("[FinnhubEarningsScheduler] {} @ {} 동기화 실패", row.symbol(), scheduledAt, e);
            }
        }

        logCycleResult(rows.size(), total, inserted, updated, skipped, failed);
    }

    private void logCycleResult(int responseRows, int processed, int inserted, int updated, int skipped, int failed) {
        // 실패율 분모는 영속화 시도된 row 수 (= total - skipped). skipped 는 Stock 미존재로 정상 무시된 케이스.
        int attempted = processed - skipped;
        double failureRate = attempted == 0 ? 0.0 : (double) failed / attempted;
        if (failureRate >= FAILURE_RATE_ERROR_THRESHOLD) {
            log.error("[FinnhubEarningsScheduler] 실패율 {}% (response={} processed={} inserted={} updated={} skipped={} failed={}) — 외부 API/DB 점검 필요",
                    (int) (failureRate * 100), responseRows, processed, inserted, updated, skipped, failed);
        } else {
            log.info("[FinnhubEarningsScheduler] 어닝 일정 갱신 완료 — response={} processed={} inserted={} updated={} skipped={} failed={}",
                    responseRows, processed, inserted, updated, skipped, failed);
        }
    }
}
