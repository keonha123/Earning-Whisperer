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
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * {@link StockMetaSyncScheduler} 단위 테스트.
 *
 * <p>{@link StockMetaSyncService} 가 mock — Service 의 영속화 로직은 별도 테스트에서 검증.
 * 본 테스트는 스케줄러의 책임만 검증:
 * <ul>
 *     <li>unique stock 추출 후 ticker 별 service 위임</li>
 *     <li>service true/false/throw 케이스의 success/failed 카운트</li>
 *     <li>실패율 ≥ 30% 시 ERROR 로그, 미만이면 INFO</li>
 *     <li>관심종목 비어있을 때 service 호출 없음</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("StockMetaSyncScheduler 단위 테스트")
class StockMetaSyncSchedulerTest {

    @Mock private StockMetaSyncService stockMetaSyncService;
    @Mock private WatchlistRepository watchlistRepository;

    @InjectMocks
    private StockMetaSyncScheduler scheduler;

    private Logger schedulerLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        schedulerLogger = (Logger) LoggerFactory.getLogger(StockMetaSyncScheduler.class);
        appender = new ListAppender<>();
        appender.start();
        schedulerLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        schedulerLogger.detachAppender(appender);
    }

    @Test
    @DisplayName("정상 케이스 — 모든 ticker 성공 시 INFO 로그")
    void 모두_성공_INFO() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.LOW)).willReturn(true);
        given(stockMetaSyncService.syncTicker(2L, "MSFT", SyncPriority.LOW)).willReturn(true);

        scheduler.syncStockMetas();

        verify(stockMetaSyncService).syncTicker(1L, "AAPL", SyncPriority.LOW);
        verify(stockMetaSyncService).syncTicker(2L, "MSFT", SyncPriority.LOW);
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage())
                .contains("success=2", "failed=0", "total=2");
    }

    @Test
    @DisplayName("service false 반환 시 failed 카운트 증가, 다음 ticker 진행")
    void service_false_failed_count() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.LOW)).willReturn(false);
        given(stockMetaSyncService.syncTicker(2L, "MSFT", SyncPriority.LOW)).willReturn(true);

        scheduler.syncStockMetas();

        // 1/2 = 50% 실패 → ERROR 로그
        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.ERROR);
        assertThat(last.getFormattedMessage())
                .contains("실패율 50%", "success=1", "failed=1");
    }

    @Test
    @DisplayName("service RuntimeException → catch 후 다음 ticker 진행, stacktrace 로그")
    void service_throw_caught() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock msft = stockOf(2L, "MSFT");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, msft));
        given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.LOW))
                .willThrow(new RuntimeException("DB constraint violation"));
        given(stockMetaSyncService.syncTicker(2L, "MSFT", SyncPriority.LOW)).willReturn(true);

        scheduler.syncStockMetas();

        // AAPL throw 후 MSFT 정상 호출되어야 — 격리 보장
        verify(stockMetaSyncService).syncTicker(2L, "MSFT", SyncPriority.LOW);

        // WARN 로그에 ticker + throwable 포함
        boolean hasWarnWithThrowable = appender.list.stream()
                .anyMatch(e -> e.getLevel() == Level.WARN
                        && e.getFormattedMessage().contains("AAPL")
                        && e.getThrowableProxy() != null);
        assertThat(hasWarnWithThrowable).isTrue();
    }

    @Test
    @DisplayName("실패율 < 30% — INFO 로그")
    void 실패율_미만_INFO() {
        // 4 ticker 중 1개 실패 = 25%
        List<Stock> stocks = List.of(
                stockOf(1L, "A"), stockOf(2L, "B"), stockOf(3L, "C"), stockOf(4L, "D"));
        given(watchlistRepository.findDistinctStocks()).willReturn(stocks);
        given(stockMetaSyncService.syncTicker(eq(1L), anyString(), eq(SyncPriority.LOW))).willReturn(false);
        given(stockMetaSyncService.syncTicker(eq(2L), anyString(), eq(SyncPriority.LOW))).willReturn(true);
        given(stockMetaSyncService.syncTicker(eq(3L), anyString(), eq(SyncPriority.LOW))).willReturn(true);
        given(stockMetaSyncService.syncTicker(eq(4L), anyString(), eq(SyncPriority.LOW))).willReturn(true);

        scheduler.syncStockMetas();

        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.INFO);
        assertThat(last.getFormattedMessage()).contains("success=3", "failed=1");
    }

    @Test
    @DisplayName("실패율 ≥ 30% — ERROR 로그")
    void 실패율_초과_ERROR() {
        // 3 ticker 중 1개 실패 = 33% ≥ 30%
        List<Stock> stocks = List.of(stockOf(1L, "A"), stockOf(2L, "B"), stockOf(3L, "C"));
        given(watchlistRepository.findDistinctStocks()).willReturn(stocks);
        given(stockMetaSyncService.syncTicker(eq(1L), anyString(), eq(SyncPriority.LOW))).willReturn(false);
        given(stockMetaSyncService.syncTicker(eq(2L), anyString(), eq(SyncPriority.LOW))).willReturn(true);
        given(stockMetaSyncService.syncTicker(eq(3L), anyString(), eq(SyncPriority.LOW))).willReturn(true);

        scheduler.syncStockMetas();

        ILoggingEvent last = latestEvent();
        assertThat(last.getLevel()).isEqualTo(Level.ERROR);
        assertThat(last.getFormattedMessage()).contains("실패율 33%");
    }

    @Test
    @DisplayName("관심종목 비어있으면 service 호출 없이 INFO skip 로그")
    void 빈_관심종목_skip() {
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of());

        scheduler.syncStockMetas();

        verify(stockMetaSyncService, never()).syncTicker(any(), any(), any());
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage()).contains("관심종목 비어있음");
    }

    @Test
    @DisplayName("Stock 의 id 가 null 인 invalid 항목은 service 호출 없이 failed 카운트")
    void invalid_stock_skip() {
        Stock valid = stockOf(1L, "AAPL");
        Stock invalid = Stock.builder().ticker("BAD").companyName("X").sector("Y").build(); // id 없음
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(valid, invalid));
        given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.LOW)).willReturn(true);

        scheduler.syncStockMetas();

        verify(stockMetaSyncService, times(1)).syncTicker(any(), any(), any());
        verify(stockMetaSyncService, never()).syncTicker(eq(null), any(), any());
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
