package com.earningwhisperer.infrastructure.finnhub;

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

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * FinnhubEarningsScheduler 단위 테스트.
 *
 * <p>FinnhubClient 는 mock — 외부 호출 없음. {@link FinnhubEarningsSyncService} 도 mock — 본 테스트는
 * scheduler 의 row 루프 + estimate 전달 + per-row try/catch 격리 동작만 검증한다. row 단위 트랜잭션
 * 격리의 실제 동작은 {@code FinnhubEarningsSyncServiceTxIsolationTest} 가 통합 테스트로 검증.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("FinnhubEarningsScheduler 단위 테스트")
class FinnhubEarningsSchedulerTest {

    @Mock private FinnhubClient finnhubClient;
    @Mock private FinnhubEarningsSyncService finnhubEarningsSyncService;

    @InjectMocks
    private FinnhubEarningsScheduler scheduler;

    @Test
    @DisplayName("응답 row 의 epsEstimate / revenueEstimate 가 upsertRow 호출에 전달된다")
    void 컨센서스_전달() {
        FinnhubCalendarRow row = new FinnhubCalendarRow(
                "AAPL",
                LocalDate.parse("2026-05-15"),
                "amc",
                new BigDecimal("1.55"),
                new BigDecimal("90000000000"));
        given(finnhubClient.fetchCalendar(any(), any(), eq(FinnhubRateLimiter.Priority.LOW)))
                .willReturn(List.of(row));
        given(finnhubEarningsSyncService.upsertRow(any(), any(), anyBoolean(), any(), any()))
                .willReturn(FinnhubEarningsSyncService.UpsertResult.INSERTED);

        scheduler.syncEarningsCalendar();

        ArgumentCaptor<BigDecimal> epsCaptor = ArgumentCaptor.forClass(BigDecimal.class);
        ArgumentCaptor<BigDecimal> revCaptor = ArgumentCaptor.forClass(BigDecimal.class);
        verify(finnhubEarningsSyncService, times(1)).upsertRow(
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
        given(finnhubEarningsSyncService.upsertRow(any(), any(), anyBoolean(), any(), any()))
                .willReturn(FinnhubEarningsSyncService.UpsertResult.INSERTED);

        scheduler.syncEarningsCalendar();

        verify(finnhubEarningsSyncService).upsertRow(
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
        given(finnhubEarningsSyncService.upsertRow(any(), any(), anyBoolean(), any(), any()))
                .willReturn(FinnhubEarningsSyncService.UpsertResult.INSERTED);

        scheduler.syncEarningsCalendar();

        verify(finnhubEarningsSyncService, times(1))
                .upsertRow(eq("MSFT"), any(Instant.class), anyBoolean(), any(), any());
    }

    @Test
    @DisplayName("응답이 비어있으면 upsertRow 호출 없음")
    void 빈_응답() {
        given(finnhubClient.fetchCalendar(any(), any(), any())).willReturn(List.of());

        scheduler.syncEarningsCalendar();

        verify(finnhubEarningsSyncService, never())
                .upsertRow(any(), any(), anyBoolean(), any(), any());
    }

    @Test
    @DisplayName("한 row 의 RuntimeException 은 catch 되고 다음 row 처리는 계속 진행된다")
    void per_row_격리_runtimeException() {
        FinnhubCalendarRow rowA = new FinnhubCalendarRow(
                "AAA", LocalDate.parse("2026-05-15"), null, null, null);
        FinnhubCalendarRow rowB = new FinnhubCalendarRow(
                "BBB", LocalDate.parse("2026-05-15"), null, null, null);
        FinnhubCalendarRow rowC = new FinnhubCalendarRow(
                "CCC", LocalDate.parse("2026-05-15"), null, null, null);

        given(finnhubClient.fetchCalendar(any(), any(), any()))
                .willReturn(List.of(rowA, rowB, rowC));

        // ticker B 만 service 가 RuntimeException — Scheduler 가 catch 후 다음 row 진행해야 한다.
        given(finnhubEarningsSyncService.upsertRow(eq("AAA"), any(), anyBoolean(), any(), any()))
                .willReturn(FinnhubEarningsSyncService.UpsertResult.INSERTED);
        given(finnhubEarningsSyncService.upsertRow(eq("BBB"), any(), anyBoolean(), any(), any()))
                .willThrow(new RuntimeException("simulated row failure"));
        given(finnhubEarningsSyncService.upsertRow(eq("CCC"), any(), anyBoolean(), any(), any()))
                .willReturn(FinnhubEarningsSyncService.UpsertResult.INSERTED);

        scheduler.syncEarningsCalendar();

        // 3개 row 모두 service 호출이 시도됐어야 한다 — B 의 실패가 C 처리를 막지 않음.
        verify(finnhubEarningsSyncService).upsertRow(eq("AAA"), any(), anyBoolean(), any(), any());
        verify(finnhubEarningsSyncService).upsertRow(eq("BBB"), any(), anyBoolean(), any(), any());
        verify(finnhubEarningsSyncService).upsertRow(eq("CCC"), any(), anyBoolean(), any(), any());
    }
}
