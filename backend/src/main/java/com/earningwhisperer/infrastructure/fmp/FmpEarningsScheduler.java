package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.earnings.EarningsCalendarService;
import com.earningwhisperer.infrastructure.fmp.dto.FmpEarningsCalendarItem;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Async;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;

/**
 * FMP `/stable/earnings-calendar` → earnings_calendar 테이블 upsert 스케줄러.
 * - 앱 시작 시 1회 (Async)
 * - 매일 UTC 06:00 갱신
 * 1 API call/day — FMP 일일 한도(250) 대비 무시할 수준.
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
public class FmpEarningsScheduler {

    private static final double FAILURE_RATE_ERROR_THRESHOLD = 0.3;

    private final FmpClient fmpClient;
    private final EarningsCalendarService earningsCalendarService;

    @Async
    @EventListener(ApplicationReadyEvent.class)
    public void syncOnStartup() {
        sync("startup");
    }

    @Scheduled(cron = "0 0 6 * * *", zone = "UTC")
    public void syncDaily() {
        sync("daily");
    }

    public void sync(String trigger) {
        LocalDate from = LocalDate.now(ZoneOffset.UTC);
        LocalDate to = from.plusDays(90);

        List<FmpEarningsCalendarItem> items = fmpClient.fetchEarningsCalendar(
                from, to, FmpRateLimiter.Priority.LOW);

        if (items.isEmpty()) {
            log.info("[FmpEarningsScheduler][{}] 응답 없음 from={} to={}", trigger, from, to);
            return;
        }

        log.info("[FmpEarningsScheduler][{}] {} 건 수신 — upsert 시작", trigger, items.size());
        int success = 0, failed = 0, skipped = 0;

        for (FmpEarningsCalendarItem item : items) {
            if (item.symbol() == null || item.date() == null) { skipped++; continue; }
            try {
                LocalDate date = LocalDate.parse(item.date());
                earningsCalendarService.upsert(
                        item.symbol(),
                        date.atStartOfDay(ZoneOffset.UTC).toInstant(),
                        true,
                        null,
                        item.epsEstimated(),
                        item.revenueEstimated());
                success++;
            } catch (Exception e) {
                failed++;
                log.warn("[FmpEarningsScheduler] {} upsert 실패: {}", item.symbol(), e.getMessage());
            }
        }

        int attempted = success + failed;
        double failureRate = attempted == 0 ? 0.0 : (double) failed / attempted;
        if (failureRate >= FAILURE_RATE_ERROR_THRESHOLD) {
            log.error("[FmpEarningsScheduler][{}] 실패율 {}% (total={} success={} failed={} skipped={})",
                    trigger, (int)(failureRate * 100), items.size(), success, failed, skipped);
        } else {
            log.info("[FmpEarningsScheduler][{}] 완료 — total={} success={} failed={} skipped={}",
                    trigger, items.size(), success, failed, skipped);
        }
    }
}
