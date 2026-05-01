package com.earningwhisperer.infrastructure.finnhub;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.watchlist.WatchlistRepository;
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
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * {@link EarningsResultSyncScheduler} 단위 테스트.
 *
 * <p>{@link EarningsResultSyncService} mock — 영속화 로직은 별도 테스트.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("EarningsResultSyncScheduler 단위 테스트")
class EarningsResultSyncSchedulerTest {

    @Mock private EarningsResultSyncService earningsResultSyncService;
    @Mock private WatchlistRepository watchlistRepository;

    @InjectMocks
    private EarningsResultSyncScheduler scheduler;

    private Logger schedulerLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        schedulerLogger = (Logger) LoggerFactory.getLogger(EarningsResultSyncScheduler.class);
        appender = new ListAppender<>();
        appender.start();
        schedulerLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        schedulerLogger.detachAppender(appender);
    }

    @Test
    @DisplayName("정상 케이스 — 모든 ticker 성공 시 INFO 로그, 신규 카운트 누적")
    void 정상_INFO() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(earningsResultSyncService.syncTicker(1L, "AAPL")).willReturn(2);
        given(earningsResultSyncService.syncTicker(2L, "MSFT")).willReturn(0);

        scheduler.syncEarningsResults();

        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.INFO);
        assertThat(last.getFormattedMessage())
                .contains("tickers=2", "success=2", "failed=0", "new=2");
    }

    @Test
    @DisplayName("service throw → catch 후 다음 ticker 진행, stacktrace 로그")
    void service_throw_caught() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(earningsResultSyncService.syncTicker(1L, "AAPL"))
                .willThrow(new RuntimeException("DB constraint violation"));
        given(earningsResultSyncService.syncTicker(2L, "MSFT")).willReturn(1);

        scheduler.syncEarningsResults();

        verify(earningsResultSyncService).syncTicker(2L, "MSFT");

        boolean hasWarnWithThrowable = appender.list.stream()
                .anyMatch(e -> e.getLevel() == Level.WARN
                        && e.getFormattedMessage().contains("AAPL")
                        && e.getThrowableProxy() != null);
        assertThat(hasWarnWithThrowable).isTrue();
    }

    @Test
    @DisplayName("실패율 ≥ 30% — ERROR 로그 승격")
    void 실패율_초과_ERROR() {
        // 3 ticker 중 1개 throw = 33% ≥ 30%
        List<Stock> stocks = List.of(stockOf(1L, "A"), stockOf(2L, "B"), stockOf(3L, "C"));
        given(watchlistRepository.findDistinctStocks()).willReturn(stocks);
        given(earningsResultSyncService.syncTicker(eq(1L), anyString()))
                .willThrow(new RuntimeException("boom"));
        given(earningsResultSyncService.syncTicker(eq(2L), anyString())).willReturn(1);
        given(earningsResultSyncService.syncTicker(eq(3L), anyString())).willReturn(0);

        scheduler.syncEarningsResults();

        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.ERROR);
        assertThat(last.getFormattedMessage()).contains("실패율 33%", "failed=1");
    }

    @Test
    @DisplayName("실패율 < 30% — INFO 로그")
    void 실패율_미만_INFO() {
        // 4 중 1 throw = 25%
        List<Stock> stocks = List.of(
                stockOf(1L, "A"), stockOf(2L, "B"), stockOf(3L, "C"), stockOf(4L, "D"));
        given(watchlistRepository.findDistinctStocks()).willReturn(stocks);
        given(earningsResultSyncService.syncTicker(eq(1L), anyString()))
                .willThrow(new RuntimeException("boom"));
        given(earningsResultSyncService.syncTicker(eq(2L), anyString())).willReturn(2);
        given(earningsResultSyncService.syncTicker(eq(3L), anyString())).willReturn(2);
        given(earningsResultSyncService.syncTicker(eq(4L), anyString())).willReturn(0);

        scheduler.syncEarningsResults();

        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.INFO);
        assertThat(last.getFormattedMessage()).contains("success=3", "failed=1", "new=4");
    }

    @Test
    @DisplayName("관심종목 비어있으면 service 호출 없이 INFO skip 로그")
    void 빈_관심종목_skip() {
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of());

        scheduler.syncEarningsResults();

        verify(earningsResultSyncService, never()).syncTicker(any(), any());
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
