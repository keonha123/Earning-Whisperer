package com.earningwhisperer.domain.stock;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarRepository;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.infrastructure.stock.LazyFetchResult;
import com.earningwhisperer.infrastructure.stock.LazyFetchService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * {@link StockDetailService} 단위 테스트.
 *
 * <p>Repository / LazyFetchService 모두 mock — DB / 외부 호출 없음.
 *
 * <p>핵심 시나리오:
 * <ul>
 *     <li>LazyFetchService 있음 + ensureExists 정상 → DB 통합 응답</li>
 *     <li>LazyFetchService 있음 + allFailed + Stock 미존재 → empty Optional</li>
 *     <li>LazyFetchService 없음 + Stock 존재 → DB 만 반환</li>
 *     <li>LazyFetchService 없음 + Stock 미존재 → empty Optional</li>
 *     <li>StockMeta null → BasicInfo null + partial=true</li>
 *     <li>chart30d 비어있음 → currentPrice null + partial=true</li>
 *     <li>earningsHistory 4건 + nextEarning 미존재</li>
 *     <li>placeholder Stock(active=false) → partial=true</li>
 *     <li>ticker 정규식 미통과 → IllegalArgumentException</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("StockDetailService 단위 테스트")
class StockDetailServiceTest {

    @Mock private StockRepository stockRepository;
    @Mock private StockMetaRepository stockMetaRepository;
    @Mock private DailyBarRepository dailyBarRepository;
    @Mock private EarningsResultRepository earningsResultRepository;
    @Mock private EarningsCalendarRepository earningsCalendarRepository;
    @Mock private LazyFetchService lazyFetchService;

    private StockDetailService service;

    @BeforeEach
    void setUp() {
        // 기본은 LazyFetchService Bean 있음 케이스로 구성
        service = new StockDetailService(
                stockRepository,
                stockMetaRepository,
                dailyBarRepository,
                earningsResultRepository,
                earningsCalendarRepository,
                Optional.of(lazyFetchService)
        );
    }

    @Nested
    @DisplayName("ticker 검증")
    class TickerValidation {

        @Test
        @DisplayName("null ticker → IllegalArgumentException")
        void null_ticker() {
            assertThatThrownBy(() -> service.getDetail(null))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("소문자 → IllegalArgumentException")
        void lowercase_ticker() {
            assertThatThrownBy(() -> service.getDetail("aapl"))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("11자 초과 → IllegalArgumentException")
        void too_long_ticker() {
            assertThatThrownBy(() -> service.getDetail("ABCDEFGHIJK"))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Nested
    @DisplayName("LazyFetchService 있음 케이스")
    class WithLazyFetch {

        @Test
        @DisplayName("ensureExists 정상 + 모든 데이터 적재 → 정상 응답 (partial=false)")
        void full_success() {
            given(lazyFetchService.ensureExists("AAPL")).willReturn(allFetchedResult("AAPL"));

            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(
                            barOf(aapl, LocalDate.parse("2026-04-30"), "180.00"),
                            barOf(aapl, LocalDate.parse("2026-04-29"), "179.50")
                    ));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl, "Q1 FY26")));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.of(calendarOf(aapl)));

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            StockDetailResponse r = result.get();
            assertThat(r.ticker()).isEqualTo("AAPL");
            assertThat(r.companyName()).isEqualTo("Apple Inc.");
            assertThat(r.sector()).isEqualTo("TECH");
            assertThat(r.active()).isTrue();
            assertThat(r.basic()).isNotNull();
            assertThat(r.basic().marketCapUsd()).isEqualByComparingTo("3000000000000");
            assertThat(r.chart30d()).hasSize(2);
            // 오름차순(과거 → 최신) 검증
            assertThat(r.chart30d().get(0).date()).isEqualTo(LocalDate.parse("2026-04-29"));
            assertThat(r.chart30d().get(1).date()).isEqualTo(LocalDate.parse("2026-04-30"));
            // currentPrice = 가장 최근 close
            assertThat(r.currentPrice()).isEqualByComparingTo("180.00");
            assertThat(r.earningsHistory()).hasSize(1);
            assertThat(r.earningsHistory().get(0).fiscalPeriodLabel()).isEqualTo("Q1 FY26");
            assertThat(r.nextEarning()).isNotNull();
            assertThat(r.partial()).isFalse();
            assertThat(r.ai()).isNull();
        }

        @Test
        @DisplayName("allFailed + Stock 미존재 → empty Optional (503)")
        void allFailed_stock_missing_returns_empty() {
            given(lazyFetchService.ensureExists("FAIL")).willReturn(allFailedResult("FAIL"));
            given(stockRepository.findByTicker("FAIL")).willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("FAIL");

            assertThat(result).isEmpty();
        }

        @Test
        @DisplayName("allFailed 이지만 Stock 존재 → DB 데이터로 응답 (partial=true)")
        void allFailed_but_stock_exists_returns_db() {
            given(lazyFetchService.ensureExists("FAIL")).willReturn(allFailedResult("FAIL"));
            Stock stock = stockOf(1L, "FAIL", "FAIL", null, false); // placeholder
            given(stockRepository.findByTicker("FAIL")).willReturn(Optional.of(stock));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("FAIL");

            assertThat(result).isPresent();
            assertThat(result.get().partial()).isTrue();
            assertThat(result.get().active()).isFalse();
        }

        @Test
        @DisplayName("ensureExists 자체가 throw → DB fallback 시도 (Stock 존재 시 정상 응답)")
        void ensureExists_throw_db_fallback() {
            given(lazyFetchService.ensureExists("AAPL"))
                    .willThrow(new RuntimeException("unexpected"));

            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl, LocalDate.parse("2026-04-30"), "180")));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl, "Q1 FY26")));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            // nextEarning null → partial=false (history 1건 존재로 만족)
            assertThat(result.get().partial()).isFalse();
        }
    }

    @Nested
    @DisplayName("LazyFetchService 없음 케이스")
    class WithoutLazyFetch {

        @BeforeEach
        void rebuildWithoutLazy() {
            service = new StockDetailService(
                    stockRepository,
                    stockMetaRepository,
                    dailyBarRepository,
                    earningsResultRepository,
                    earningsCalendarRepository,
                    Optional.empty()
            );
        }

        @Test
        @DisplayName("Stock 존재 → DB 만 반환")
        void stock_exists_returns_db_only() {
            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl, LocalDate.parse("2026-04-30"), "180")));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl, "Q1 FY26")));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            verify(lazyFetchService, never()).ensureExists(anyString());
        }

        @Test
        @DisplayName("Stock 미존재 → empty Optional (503)")
        void stock_missing_returns_empty() {
            given(stockRepository.findByTicker("UNKNOWN")).willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("UNKNOWN");

            assertThat(result).isEmpty();
            verify(lazyFetchService, never()).ensureExists(anyString());
        }
    }

    @Nested
    @DisplayName("partial 판정")
    class PartialFlag {

        @Test
        @DisplayName("StockMeta null → BasicInfo null + partial=true")
        void meta_null_partial() {
            given(lazyFetchService.ensureExists("AAPL"))
                    .willReturn(allFetchedResult("AAPL"));
            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl, LocalDate.parse("2026-04-30"), "180")));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl, "Q1 FY26")));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            assertThat(result.get().basic()).isNull();
            assertThat(result.get().partial()).isTrue();
        }

        @Test
        @DisplayName("chart30d 비어있음 → currentPrice null + partial=true")
        void chart_empty_partial() {
            given(lazyFetchService.ensureExists("AAPL"))
                    .willReturn(allFetchedResult("AAPL"));
            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl, "Q1 FY26")));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            assertThat(result.get().chart30d()).isEmpty();
            assertThat(result.get().currentPrice()).isNull();
            assertThat(result.get().partial()).isTrue();
        }

        @Test
        @DisplayName("earningsHistory 비어있음 + nextEarning 미존재 → partial=true")
        void earnings_both_missing_partial() {
            given(lazyFetchService.ensureExists("AAPL"))
                    .willReturn(allFetchedResult("AAPL"));
            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl, LocalDate.parse("2026-04-30"), "180")));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            assertThat(result.get().partial()).isTrue();
        }

        @Test
        @DisplayName("earningsHistory 비어있어도 nextEarning 있으면 partial=false")
        void next_earning_only_not_partial() {
            given(lazyFetchService.ensureExists("AAPL"))
                    .willReturn(allFetchedResult("AAPL"));
            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl, LocalDate.parse("2026-04-30"), "180")));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.of(calendarOf(aapl)));

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            assertThat(result.get().partial()).isFalse();
        }

        @Test
        @DisplayName("placeholder Stock (active=false) → partial=true (다른 데이터 다 있어도)")
        void placeholder_stock_always_partial() {
            given(lazyFetchService.ensureExists("XYZ"))
                    .willReturn(allFetchedResult("XYZ"));
            Stock xyz = stockOf(1L, "XYZ", "XYZ", null, false);
            given(stockRepository.findByTicker("XYZ")).willReturn(Optional.of(xyz));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(xyz)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(xyz, LocalDate.parse("2026-04-30"), "10")));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(xyz, "Q1 FY26")));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("XYZ");

            assertThat(result).isPresent();
            assertThat(result.get().active()).isFalse();
            assertThat(result.get().partial()).isTrue();
        }
    }

    @Nested
    @DisplayName("응답 데이터 정렬/변환")
    class DataMapping {

        @Test
        @DisplayName("earningsHistory 4건 정상 매핑")
        void earnings_4_mapped() {
            given(lazyFetchService.ensureExists("AAPL"))
                    .willReturn(allFetchedResult("AAPL"));
            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl, LocalDate.parse("2026-04-30"), "180")));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(
                            earningsOf(aapl, "Q1 FY26"),
                            earningsOf(aapl, "Q4 FY25"),
                            earningsOf(aapl, "Q3 FY25"),
                            earningsOf(aapl, "Q2 FY25")
                    ));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            assertThat(result.get().earningsHistory()).hasSize(4);
            assertThat(result.get().earningsHistory().get(0).fiscalPeriodLabel()).isEqualTo("Q1 FY26");
            // announcedAt epoch second 정상 변환
            assertThat(result.get().earningsHistory().get(0).announcedAt())
                    .isEqualTo(Instant.parse("2026-04-30T13:00:00Z").getEpochSecond());
        }

        @Test
        @DisplayName("currentPrice 는 chart30d 마지막 (가장 최근) close")
        void current_price_last_close() {
            given(lazyFetchService.ensureExists("AAPL"))
                    .willReturn(allFetchedResult("AAPL"));
            Stock aapl = stockOf(1L, "AAPL", "Apple Inc.", "TECH", true);
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            // Repository 는 DESC 반환 → 첫 번째가 가장 최신
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(
                            barOf(aapl, LocalDate.parse("2026-04-30"), "200.50"),
                            barOf(aapl, LocalDate.parse("2026-04-29"), "199.00"),
                            barOf(aapl, LocalDate.parse("2026-04-28"), "198.00")
                    ));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl, "Q1 FY26")));
            given(earningsCalendarRepository.findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(
                    eqLong(1L), any(Instant.class)))
                    .willReturn(Optional.empty());

            Optional<StockDetailResponse> result = service.getDetail("AAPL");

            assertThat(result).isPresent();
            assertThat(result.get().currentPrice()).isEqualByComparingTo("200.50");
            // chart 는 오름차순(과거 → 최신)
            assertThat(result.get().chart30d().get(0).date()).isEqualTo(LocalDate.parse("2026-04-28"));
            assertThat(result.get().chart30d().get(2).date()).isEqualTo(LocalDate.parse("2026-04-30"));
        }
    }

    // ─────────── helpers ───────────

    private static Long eqLong(Long val) {
        return org.mockito.ArgumentMatchers.eq(val);
    }

    private static LazyFetchResult allFetchedResult(String ticker) {
        return new LazyFetchResult(
                ticker, true, true, true, true, false,
                true, true, true, true);
    }

    private static LazyFetchResult allFailedResult(String ticker) {
        return new LazyFetchResult(
                ticker, false, false, false, false, false,
                true, false, false, false);
    }

    private static Stock stockOf(Long id, String ticker, String companyName, String sector, boolean active) {
        Stock s = Stock.builder().ticker(ticker).companyName(companyName).sector(sector).build();
        if (!active) {
            s.deactivate();
        }
        setField(Stock.class, s, "id", id);
        return s;
    }

    private static StockMeta metaOf(Stock stock) {
        return StockMeta.builder()
                .stock(stock)
                .marketCapUsd(new BigDecimal("3000000000000"))
                .high52w(new BigDecimal("200.30"))
                .low52w(new BigDecimal("75.60"))
                .dividendYield(new BigDecimal("0.0049"))
                .build();
    }

    private static DailyBar barOf(Stock stock, LocalDate date, String close) {
        return DailyBar.builder()
                .stock(stock)
                .barDate(date)
                .closePrice(new BigDecimal(close))
                .volume(1_000_000L)
                .build();
    }

    private static EarningsResult earningsOf(Stock stock, String fiscalLabel) {
        return EarningsResult.builder()
                .stock(stock)
                .announcedAt(Instant.parse("2026-04-30T13:00:00Z"))
                .fiscalPeriodLabel(fiscalLabel)
                .epsEstimate(new BigDecimal("1.20"))
                .epsActual(new BigDecimal("1.35"))
                .surprisePercent(new BigDecimal("12.50"))
                .priceReactionPercent(new BigDecimal("3.45"))
                .build();
    }

    private static EarningsCalendar calendarOf(Stock stock) {
        return EarningsCalendar.builder()
                .stock(stock)
                .scheduledAt(Instant.parse("2026-07-30T13:00:00Z"))
                .confirmed(true)
                .epsEstimate(new BigDecimal("1.40"))
                .revenueEstimate(new BigDecimal("100000000000"))
                .build();
    }

    private static <T> void setField(Class<T> clazz, Object instance, String fieldName, Object value) {
        try {
            Field field = clazz.getDeclaredField(fieldName);
            field.setAccessible(true);
            field.set(instance, value);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
