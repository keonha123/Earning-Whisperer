package com.earningwhisperer.infrastructure.fmp;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.watchlist.WatchlistRepository;
import com.earningwhisperer.global.common.SyncPriority;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Field;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * {@link DailyBarSyncScheduler} 단위 테스트.
 *
 * <p>{@link DailyBarSyncService} mock — 영속화 로직은 별도 테스트.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("DailyBarSyncScheduler 단위 테스트")
class DailyBarSyncSchedulerTest {

    @Mock private DailyBarSyncService dailyBarSyncService;
    @Mock private WatchlistRepository watchlistRepository;

    @InjectMocks
    private DailyBarSyncScheduler scheduler;

    private Logger schedulerLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        schedulerLogger = (Logger) LoggerFactory.getLogger(DailyBarSyncScheduler.class);
        appender = new ListAppender<>();
        appender.start();
        schedulerLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        schedulerLogger.detachAppender(appender);
    }

    @Test
    @DisplayName("정상 케이스 — service 가 양수 반환, INFO 로그에 bars 카운트 누적")
    void 정상_INFO() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.LOW)).willReturn(30);
        given(dailyBarSyncService.syncTicker(2L, "MSFT", 30, SyncPriority.LOW)).willReturn(28);

        scheduler.syncDailyBars();

        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.INFO);
        assertThat(last.getFormattedMessage())
                .contains("tickers=2", "success=2", "failed=0", "bars=58");
    }

    @Test
    @DisplayName("service 0 반환 → failed 카운트 증가, 다음 ticker 진행")
    void service_0_failed() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.LOW)).willReturn(0);
        given(dailyBarSyncService.syncTicker(2L, "MSFT", 30, SyncPriority.LOW)).willReturn(15);

        scheduler.syncDailyBars();

        // 1/2 = 50% 실패 → ERROR
        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.ERROR);
        assertThat(last.getFormattedMessage())
                .contains("실패율 50%", "success=1", "failed=1", "bars=15");
    }

    @Test
    @DisplayName("service throw → catch 후 다음 ticker 진행, stacktrace 로그")
    void service_throw_caught() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.LOW))
                .willThrow(new RuntimeException("JPA constraint"));
        given(dailyBarSyncService.syncTicker(2L, "MSFT", 30, SyncPriority.LOW)).willReturn(20);

        scheduler.syncDailyBars();

        verify(dailyBarSyncService).syncTicker(2L, "MSFT", 30, SyncPriority.LOW);

        boolean hasWarnWithThrowable = appender.list.stream()
                .anyMatch(e -> e.getLevel() == Level.WARN
                        && e.getFormattedMessage().contains("AAPL")
                        && e.getThrowableProxy() != null);
        assertThat(hasWarnWithThrowable).isTrue();
    }

    @Test
    @DisplayName("실패율 < 30% — INFO")
    void 실패율_미만_INFO() {
        // 4 중 1 실패 = 25%
        List<Stock> stocks = List.of(
                stockOf(1L, "A"), stockOf(2L, "B"), stockOf(3L, "C"), stockOf(4L, "D"));
        given(watchlistRepository.findDistinctStocks()).willReturn(stocks);
        given(dailyBarSyncService.syncTicker(eq(1L), anyString(), anyInt(), eq(SyncPriority.LOW))).willReturn(0);
        given(dailyBarSyncService.syncTicker(eq(2L), anyString(), anyInt(), eq(SyncPriority.LOW))).willReturn(30);
        given(dailyBarSyncService.syncTicker(eq(3L), anyString(), anyInt(), eq(SyncPriority.LOW))).willReturn(30);
        given(dailyBarSyncService.syncTicker(eq(4L), anyString(), anyInt(), eq(SyncPriority.LOW))).willReturn(30);

        scheduler.syncDailyBars();

        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
    }

    @Test
    @DisplayName("관심종목 비어있으면 service 호출 없이 skip")
    void 빈_관심종목_skip() {
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of());

        scheduler.syncDailyBars();

        verify(dailyBarSyncService, never()).syncTicker(any(), any(), anyInt(), any());
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage()).contains("관심종목 비어있음");
    }

    // ─────────── helpers ───────────

    private ILoggingEvent latestEvent() {
        return appender.list.get(appender.list.size() - 1);
    }

    private static Stock stockOf(Long id, String ticker) {
        Stock s = Stock.builder().ticker(ticker).companyName("Co").sector("TECH").build();
        try {
            Field idField = Stock.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(s, id);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return s;
    }
}
