package com.earningwhisperer.infrastructure.fmp;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.earningwhisperer.domain.portfolio.PositionRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
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
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.lenient;
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
    @Mock private PositionRepository positionRepository;
    @Mock private StockRepository stockRepository;

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

        // 기본 stub — 각 테스트가 필요 시 override. lenient 로 strict stubbing 우회.
        lenient().when(positionRepository.findDistinctTickers()).thenReturn(List.of());
        lenient().when(stockRepository.findByTickerIn(anyCollection())).thenReturn(List.of());
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
    @DisplayName("watchlist + position 모두 비어있으면 service 호출 없이 skip")
    void 빈_관심종목_skip() {
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of());

        scheduler.syncDailyBars();

        verify(dailyBarSyncService, never()).syncTicker(any(), any(), anyInt(), any());
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage()).contains("watchlist + position 비어있음");
    }

    @Test
    @DisplayName("watchlist 만 있고 position 없음 → 기존 동작과 동일")
    void watchlist만_있는_경우() {
        Stock aapl = stockOf(1L, "AAPL");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl));
        given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.LOW)).willReturn(30);

        scheduler.syncDailyBars();

        verify(dailyBarSyncService).syncTicker(1L, "AAPL", 30, SyncPriority.LOW);
        verify(dailyBarSyncService, never()).syncTicker(eq(2L), anyString(), anyInt(), any());
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage()).contains("tickers=1", "success=1");
    }

    @Test
    @DisplayName("position 만 있고 watchlist 없음 → position 기반 sync")
    void position만_있는_경우() {
        Stock nvda = stockOf(10L, "NVDA");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of());
        given(positionRepository.findDistinctTickers()).willReturn(List.of("NVDA"));
        given(stockRepository.findByTickerIn(List.of("NVDA"))).willReturn(List.of(nvda));
        given(dailyBarSyncService.syncTicker(10L, "NVDA", 30, SyncPriority.LOW)).willReturn(30);

        scheduler.syncDailyBars();

        verify(dailyBarSyncService).syncTicker(10L, "NVDA", 30, SyncPriority.LOW);
        assertThat(latestEvent().getLevel()).isEqualTo(Level.INFO);
        assertThat(latestEvent().getFormattedMessage()).contains("tickers=1", "success=1", "bars=30");
    }

    @Test
    @DisplayName("watchlist + position ticker 겹침 → dedup 후 한 번만 sync")
    void watchlist_position_ticker_겹침_dedup() {
        Stock aapl = stockOf(1L, "AAPL");
        Stock nvda = stockOf(10L, "NVDA");
        // watchlist: AAPL, NVDA
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of(aapl, nvda));
        // position: NVDA, TSLA — NVDA 겹침
        given(positionRepository.findDistinctTickers()).willReturn(List.of("NVDA", "TSLA"));
        Stock tsla = stockOf(11L, "TSLA");
        // findByTickerIn 은 stocks 테이블에서 매칭되는 것만 반환 — NVDA/TSLA 둘 다 등록되어 있다고 가정
        given(stockRepository.findByTickerIn(List.of("NVDA", "TSLA"))).willReturn(List.of(nvda, tsla));
        given(dailyBarSyncService.syncTicker(eq(1L), eq("AAPL"), anyInt(), any())).willReturn(30);
        given(dailyBarSyncService.syncTicker(eq(10L), eq("NVDA"), anyInt(), any())).willReturn(30);
        given(dailyBarSyncService.syncTicker(eq(11L), eq("TSLA"), anyInt(), any())).willReturn(30);

        scheduler.syncDailyBars();

        // NVDA 는 한 번만 호출되어야 함
        verify(dailyBarSyncService).syncTicker(10L, "NVDA", 30, SyncPriority.LOW);
        verify(dailyBarSyncService).syncTicker(1L, "AAPL", 30, SyncPriority.LOW);
        verify(dailyBarSyncService).syncTicker(11L, "TSLA", 30, SyncPriority.LOW);
        assertThat(latestEvent().getFormattedMessage()).contains("tickers=3", "success=3");
    }

    @Test
    @DisplayName("position ticker 가 stocks 테이블에 미등록인 경우 — debug 로깅 + skip")
    void position_ticker_stocks_미등록_skip() {
        schedulerLogger.setLevel(Level.DEBUG);
        Stock nvda = stockOf(10L, "NVDA");
        given(watchlistRepository.findDistinctStocks()).willReturn(List.of());
        // position 에 2개 있지만 stocks 테이블엔 NVDA 만 — UNKNOWN_TICKER 미등록
        given(positionRepository.findDistinctTickers()).willReturn(List.of("NVDA", "UNKNOWN_TICKER"));
        given(stockRepository.findByTickerIn(List.of("NVDA", "UNKNOWN_TICKER"))).willReturn(List.of(nvda));
        given(dailyBarSyncService.syncTicker(10L, "NVDA", 30, SyncPriority.LOW)).willReturn(30);

        scheduler.syncDailyBars();

        verify(dailyBarSyncService).syncTicker(10L, "NVDA", 30, SyncPriority.LOW);
        boolean hasDebugSkipLog = appender.list.stream()
                .anyMatch(e -> e.getLevel() == Level.DEBUG
                        && e.getFormattedMessage().contains("stocks 테이블에 미등록"));
        assertThat(hasDebugSkipLog).isTrue();
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
