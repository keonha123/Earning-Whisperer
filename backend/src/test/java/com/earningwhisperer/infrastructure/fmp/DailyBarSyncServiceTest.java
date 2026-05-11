package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.DailyBar;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.fmp.dto.FmpHistoricalBar;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * {@link DailyBarSyncService} 단위 테스트.
 *
 * <p>FmpClient / Repository mock — 외부 호출 / DB 미접근.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("DailyBarSyncService 단위 테스트")
class DailyBarSyncServiceTest {

    @Mock private FmpClient fmpClient;
    @Mock private StockRepository stockRepository;
    @Mock private DailyBarRepository dailyBarRepository;

    @InjectMocks
    private DailyBarSyncService service;

    private Stock aapl;

    @BeforeEach
    void setUp() {
        aapl = stockOf(1L, "AAPL");
    }

    @Test
    @DisplayName("신규 bar → 새 DailyBar save, processed 카운트 반환")
    void 신규_bar_save() {
        given(fmpClient.fetchHistorical(eq("AAPL"), eq(30), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(List.of(
                        barOf("2026-04-30", "175.0", 50_000_000L),
                        barOf("2026-04-29", "174.5", 48_000_000L)));
        given(stockRepository.findById(1L)).willReturn(Optional.of(aapl));
        given(dailyBarRepository.findByStock_IdAndBarDate(eq(1L), any(LocalDate.class)))
                .willReturn(Optional.empty());

        int processed = service.syncTicker(1L, "AAPL", 30, SyncPriority.LOW);

        assertThat(processed).isEqualTo(2);
        ArgumentCaptor<DailyBar> captor = ArgumentCaptor.forClass(DailyBar.class);
        verify(dailyBarRepository, times(2)).save(captor.capture());
        List<DailyBar> saved = captor.getAllValues();
        assertThat(saved).extracting(DailyBar::getBarDate)
                .containsExactly(LocalDate.parse("2026-04-30"), LocalDate.parse("2026-04-29"));
        assertThat(saved.get(0).getClosePrice()).isEqualByComparingTo("175.0");
        assertThat(saved.get(0).getVolume()).isEqualTo(50_000_000L);
        // 모든 새 DailyBar 가 reattached stock 으로 영속화되어야 함 (LAZY proxy 방지).
        assertThat(saved).allMatch(b -> b.getStock() == aapl);
    }

    @Test
    @DisplayName("기존 bar 있으면 updateClose, save 없음")
    void 기존_bar_update() {
        DailyBar existing = DailyBar.builder()
                .stock(aapl)
                .barDate(LocalDate.parse("2026-04-30"))
                .closePrice(new BigDecimal("100.0"))
                .volume(1L)
                .build();

        given(fmpClient.fetchHistorical(eq("AAPL"), eq(30), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(List.of(barOf("2026-04-30", "175.0", 50_000_000L)));
        given(stockRepository.findById(1L)).willReturn(Optional.of(aapl));
        given(dailyBarRepository.findByStock_IdAndBarDate(1L, LocalDate.parse("2026-04-30")))
                .willReturn(Optional.of(existing));

        int processed = service.syncTicker(1L, "AAPL", 30, SyncPriority.LOW);

        assertThat(processed).isEqualTo(1);
        verify(dailyBarRepository, never()).save(any(DailyBar.class));
        assertThat(existing.getClosePrice()).isEqualByComparingTo("175.0");
        assertThat(existing.getVolume()).isEqualTo(50_000_000L);
    }

    @Test
    @DisplayName("historical 빈 응답 → 0 반환, Stock reattach / save 미진입")
    void 빈_응답_0() {
        given(fmpClient.fetchHistorical(eq("AAPL"), eq(30), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(List.of());

        int processed = service.syncTicker(1L, "AAPL", 30, SyncPriority.LOW);

        assertThat(processed).isZero();
        verify(stockRepository, never()).findById(any());
        verify(dailyBarRepository, never()).save(any(DailyBar.class));
    }

    @Test
    @DisplayName("Stock 미존재 (stockId / ticker 둘 다) → 0 반환, save 없음")
    void stock_미존재_0() {
        given(fmpClient.fetchHistorical(eq("AAPL"), eq(30), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(List.of(barOf("2026-04-30", "175.0", 1L)));
        given(stockRepository.findById(1L)).willReturn(Optional.empty());
        given(stockRepository.findByTicker("AAPL")).willReturn(Optional.empty());

        int processed = service.syncTicker(1L, "AAPL", 30, SyncPriority.LOW);

        assertThat(processed).isZero();
        verify(dailyBarRepository, never()).save(any(DailyBar.class));
    }

    @Test
    @DisplayName("응답 bar 의 date/close 가 null 이면 해당 row skip, 다른 row 영속화")
    void invalid_bar_skip() {
        FmpHistoricalBar invalid = new FmpHistoricalBar(null, new BigDecimal("100"), 1L);
        FmpHistoricalBar valid = barOf("2026-04-30", "175.0", 1L);

        given(fmpClient.fetchHistorical(eq("AAPL"), eq(30), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(List.of(invalid, valid));
        given(stockRepository.findById(1L)).willReturn(Optional.of(aapl));
        given(dailyBarRepository.findByStock_IdAndBarDate(eq(1L), any(LocalDate.class)))
                .willReturn(Optional.empty());

        int processed = service.syncTicker(1L, "AAPL", 30, SyncPriority.LOW);

        assertThat(processed).isEqualTo(1);
        verify(dailyBarRepository, times(1)).save(any(DailyBar.class));
    }

    @Test
    @DisplayName("stockId 미존재여도 ticker fallback 으로 reattach → 정상 적재")
    void ticker_fallback_reattach() {
        given(fmpClient.fetchHistorical(eq("AAPL"), eq(30), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(List.of(barOf("2026-04-30", "175.0", 1L)));
        given(stockRepository.findById(99L)).willReturn(Optional.empty());
        given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
        // reattached stock 의 id 는 1L 이므로 lookup 도 1L 키로 일어남
        given(dailyBarRepository.findByStock_IdAndBarDate(eq(1L), any(LocalDate.class)))
                .willReturn(Optional.empty());

        int processed = service.syncTicker(99L, "AAPL", 30, SyncPriority.LOW);

        assertThat(processed).isEqualTo(1);
        verify(dailyBarRepository, times(1)).save(any(DailyBar.class));
    }

    // ─────────── helpers ───────────

    private static Stock stockOf(Long id, String ticker) {
        Stock s = Stock.builder().ticker(ticker).companyName("Co").sector("TECH").build();
        setId(s, id);
        return s;
    }

    private static FmpHistoricalBar barOf(String date, String close, Long volume) {
        return new FmpHistoricalBar(LocalDate.parse(date), new BigDecimal(close), volume);
    }

    private static void setId(Stock stock, Long id) {
        try {
            Field idField = Stock.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(stock, id);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
