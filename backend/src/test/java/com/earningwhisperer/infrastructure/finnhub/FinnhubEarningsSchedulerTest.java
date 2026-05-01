package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.earnings.EarningsCalendarService;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubCalendarRow;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * FinnhubEarningsScheduler 단위 테스트.
 *
 * <p>FinnhubClient 는 mock — 외부 호출 없음. EarningsCalendarService 호출 시 컨센서스 estimate 가
 * 함께 전달되는지를 검증한다 (Phase 2-B 컨센서스 백필).
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("FinnhubEarningsScheduler 단위 테스트")
class FinnhubEarningsSchedulerTest {

    @Mock private FinnhubClient finnhubClient;
    @Mock private EarningsCalendarService earningsCalendarService;

    @InjectMocks
    private FinnhubEarningsScheduler scheduler;

    @Test
    @DisplayName("응답 row 의 epsEstimate / revenueEstimate 가 upsert 호출에 전달된다")
    void 컨센서스_전달() {
        FinnhubCalendarRow row = new FinnhubCalendarRow(
                "AAPL",
                LocalDate.parse("2026-05-15"),
                "amc",
                new BigDecimal("1.55"),
                new BigDecimal("90000000000"));
        given(finnhubClient.fetchCalendar(any(), any(), eq(FinnhubRateLimiter.Priority.LOW)))
                .willReturn(List.of(row));

        scheduler.syncEarningsCalendar();

        ArgumentCaptor<BigDecimal> epsCaptor = ArgumentCaptor.forClass(BigDecimal.class);
        ArgumentCaptor<BigDecimal> revCaptor = ArgumentCaptor.forClass(BigDecimal.class);
        verify(earningsCalendarService, times(1)).upsert(
                eq("AAPL"),
                any(Instant.class),
                eq(true),
                epsCaptor.capture(),
                revCaptor.capture());

        assertThat(epsCaptor.getValue()).isEqualByComparingTo("1.55");
        assertThat(revCaptor.getValue()).isEqualByComparingTo("90000000000");
    }

    @Test
    @DisplayName("estimate 가 null 이면 null 그대로 전달 (Finnhub 응답 미제공 케이스)")
    void 컨센서스_null() {
        FinnhubCalendarRow row = new FinnhubCalendarRow(
                "AAPL",
                LocalDate.parse("2026-05-15"),
                null,
                null,
                null);
        given(finnhubClient.fetchCalendar(any(), any(), any()))
                .willReturn(List.of(row));

        scheduler.syncEarningsCalendar();

        verify(earningsCalendarService).upsert(
                eq("AAPL"),
                any(Instant.class),
                eq(true),
                eq(null),
                eq(null));
    }

    @Test
    @DisplayName("date 또는 symbol 이 null 인 row 는 skip")
    void invalid_row_skip() {
        FinnhubCalendarRow noDate = new FinnhubCalendarRow("AAPL", null, null, null, null);
        FinnhubCalendarRow noSymbol = new FinnhubCalendarRow(
                null, LocalDate.parse("2026-05-15"), null, null, null);
        FinnhubCalendarRow valid = new FinnhubCalendarRow(
                "MSFT", LocalDate.parse("2026-05-15"), null,
                new BigDecimal("3.00"), null);

        given(finnhubClient.fetchCalendar(any(), any(), any()))
                .willReturn(List.of(noDate, noSymbol, valid));

        scheduler.syncEarningsCalendar();

        verify(earningsCalendarService, times(1))
                .upsert(eq("MSFT"), any(Instant.class), anyBoolean(), any(), any());
    }

    @Test
    @DisplayName("응답이 비어있으면 upsert 호출 없음")
    void 빈_응답() {
        given(finnhubClient.fetchCalendar(any(), any(), any())).willReturn(List.of());

        scheduler.syncEarningsCalendar();

        verify(earningsCalendarService, never())
                .upsert(any(), any(), anyBoolean(), any(), any());
    }
}
