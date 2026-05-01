package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.earnings.EarningsCalendarService;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubCalendarRow;
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
 * <p>외부 API 호출 책임은 {@link FinnhubClient} 로, 분당 burst 제어는
 * {@link FinnhubRateLimiter} 로 분리되어 있고 본 클래스는 영속화 로직만 담당한다.
 */
@Slf4j
@Component
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
public class FinnhubEarningsScheduler {

    private final FinnhubClient finnhubClient;
    private final EarningsCalendarService earningsCalendarService;

    public FinnhubEarningsScheduler(FinnhubClient finnhubClient,
                                    EarningsCalendarService earningsCalendarService) {
        this.finnhubClient = finnhubClient;
        this.earningsCalendarService = earningsCalendarService;
    }

    /** 매일 오전 6시 UTC, 향후 30일 어닝 일정 갱신 */
    @Scheduled(cron = "0 0 6 * * *", zone = "UTC")
    public void syncEarningsCalendar() {
        LocalDate from = LocalDate.now(ZoneOffset.UTC);
        LocalDate to = from.plusDays(30);

        List<FinnhubCalendarRow> rows = finnhubClient.fetchCalendar(
                from, to, FinnhubRateLimiter.Priority.LOW);

        if (rows.isEmpty()) {
            log.info("[FinnhubEarningsScheduler] 어닝 일정 응답 없음 from={} to={}", from, to);
            return;
        }

        int upserted = 0;
        for (FinnhubCalendarRow row : rows) {
            if (row.date() == null || row.symbol() == null) continue;
            Instant scheduledAt = row.date().atStartOfDay(ZoneOffset.UTC).toInstant();
            earningsCalendarService.upsert(row.symbol(), scheduledAt, true);
            upserted++;
        }
        log.info("[FinnhubEarningsScheduler] 어닝 일정 갱신 완료: {}건 (응답 {}건)",
                upserted, rows.size());
    }
}
