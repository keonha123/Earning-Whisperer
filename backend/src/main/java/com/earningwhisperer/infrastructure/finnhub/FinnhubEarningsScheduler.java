package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.earnings.EarningsCalendarService;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.List;

@Slf4j
@Component
@ConditionalOnProperty(name = "finnhub.api-key", matchIfMissing = false)
public class FinnhubEarningsScheduler {

    private final RestClient restClient;
    private final FinnhubProperties properties;
    private final EarningsCalendarService earningsCalendarService;

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ISO_LOCAL_DATE;

    public FinnhubEarningsScheduler(
            @Qualifier("finnhubRestClient") RestClient restClient,
            FinnhubProperties properties,
            EarningsCalendarService earningsCalendarService) {
        this.restClient = restClient;
        this.properties = properties;
        this.earningsCalendarService = earningsCalendarService;
    }

    /** 매일 오전 6시 UTC, 향후 30일 어닝 일정 갱신 */
    @Scheduled(cron = "0 0 6 * * *", zone = "UTC")
    public void syncEarningsCalendar() {
        String from = LocalDate.now(ZoneOffset.UTC).format(DATE_FMT);
        String to   = LocalDate.now(ZoneOffset.UTC).plusDays(30).format(DATE_FMT);

        try {
            EarningsCalendarResponse response = restClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/calendar/earnings")
                            .queryParam("from", from)
                            .queryParam("to", to)
                            .queryParam("token", properties.apiKey())
                            .build())
                    .retrieve()
                    .body(EarningsCalendarResponse.class);

            if (response == null || response.earningsCalendar() == null) return;

            for (EarningsEntry entry : response.earningsCalendar()) {
                if (entry.date() == null || entry.symbol() == null) continue;
                Instant scheduledAt = LocalDate.parse(entry.date(), DATE_FMT)
                        .atStartOfDay(ZoneOffset.UTC).toInstant();
                earningsCalendarService.upsert(entry.symbol(), scheduledAt, true);
            }
            log.info("[FinnhubEarningsScheduler] 어닝 일정 갱신 완료: {}건",
                    response.earningsCalendar().size());
        } catch (RestClientException e) {
            log.error("[FinnhubEarningsScheduler] Finnhub 호출 실패: {}", e.getMessage());
        }
    }

    record EarningsCalendarResponse(
            @JsonProperty("earningsCalendar") List<EarningsEntry> earningsCalendar) {}

    record EarningsEntry(String symbol, String date) {}
}
