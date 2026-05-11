package com.earningwhisperer.infrastructure.stock;

import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.DailyBar;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockMeta;
import com.earningwhisperer.domain.stock.StockMetaRepository;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.finnhub.EarningsResultSyncService;
import com.earningwhisperer.infrastructure.fmp.DailyBarSyncService;
import com.earningwhisperer.infrastructure.fmp.FmpClient;
import com.earningwhisperer.infrastructure.fmp.FmpRateLimiter;
import com.earningwhisperer.infrastructure.fmp.StockMetaSyncService;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * {@link LazyFetchService} 단위 테스트.
 *
 * <p>외부 클라이언트 / Sync service / Repository 모두 mock — 외부 호출 / DB 미접근.
 * 검증 포인트:
 * <ul>
 *     <li>Stock 미존재 + profile 정상 → Stock 등록(active=true) + 모든 단계 fetch</li>
 *     <li>Stock 미존재 + profile 빈 결과 → placeholder Stock(active=false) + 메타/일봉/어닝 단계 진행</li>
 *     <li>Stock 존재 + StockMeta 만 없음 → StockMeta 만 fetch, 다른 단계 skip</li>
 *     <li>Stock 존재 + 모두 적재됨 → 아무것도 fetch 안 함</li>
 *     <li>한 단계 throw → 다른 단계 계속 진행, partial result 반환</li>
 *     <li>ticker 정규식 미통과 → IllegalArgumentException</li>
 * </ul>
 *
 * <p>{@code @MockitoSettings(strictness = LENIENT)}: 테스트마다 호출되지 않는 stub 가
 * 일부 존재 (단계별 skip 조건 검증). UnnecessaryStubbing 회피.
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("LazyFetchService 단위 테스트")
class LazyFetchServiceTest {

    @Mock private StockRepository stockRepository;
    @Mock private StockMetaRepository stockMetaRepository;
    @Mock private DailyBarRepository dailyBarRepository;
    @Mock private EarningsResultRepository earningsResultRepository;

    @Mock private FmpClient fmpClient;
    @Mock private StockMetaSyncService stockMetaSyncService;
    @Mock private DailyBarSyncService dailyBarSyncService;
    @Mock private EarningsResultSyncService earningsResultSyncService;

    @InjectMocks
    private LazyFetchService service;

    @Nested
    @DisplayName("ticker 검증")
    class TickerValidation {

        @Test
        @DisplayName("null ticker → IllegalArgumentException")
        void null_ticker() {
            assertThatThrownBy(() -> service.ensureExists(null))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("빈 문자열 → IllegalArgumentException")
        void empty_ticker() {
            assertThatThrownBy(() -> service.ensureExists(""))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("소문자 포함 → IllegalArgumentException")
        void lowercase_ticker() {
            assertThatThrownBy(() -> service.ensureExists("aapl"))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("11자 초과 → IllegalArgumentException")
        void too_long_ticker() {
            assertThatThrownBy(() -> service.ensureExists("ABCDEFGHIJK"))
                    .isInstanceOf(IllegalArgumentException.class);
        }

        @Test
        @DisplayName("BRK.B (마침표) — 정상 통과")
        void dot_ticker_ok() {
            // Stock 이미 존재 + 모든 데이터 적재됨으로 stub — 실제 외부 호출 X
            Stock stock = stockOf(1L, "BRK.B");
            given(stockRepository.findByTicker("BRK.B")).willReturn(Optional.of(stock));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(stock)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(stock)));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(stock)));

            LazyFetchResult result = service.ensureExists("BRK.B");

            assertThat(result.ticker()).isEqualTo("BRK.B");
            assertThat(result.anyFetched()).isFalse();
            // 어떤 단계도 attempt 안 됨 → allFailed=false (정상 캐시 hit)
            assertThat(result.stockAttempted()).isFalse();
            assertThat(result.metaAttempted()).isFalse();
            assertThat(result.dailyBarsAttempted()).isFalse();
            assertThat(result.earningsAttempted()).isFalse();
            assertThat(result.allFailed()).isFalse();
        }

        @Test
        @DisplayName("BF-B (하이픈) — 정상 통과")
        void hyphen_ticker_ok() {
            Stock stock = stockOf(1L, "BF-B");
            given(stockRepository.findByTicker("BF-B")).willReturn(Optional.of(stock));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(stock)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(stock)));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(stock)));

            LazyFetchResult result = service.ensureExists("BF-B");

            assertThat(result.anyFetched()).isFalse();
        }
    }

    @Nested
    @DisplayName("Stock 미존재 케이스")
    class StockMissing {

        @Test
        @DisplayName("profile 정상 → Stock 등록(active=true) + 모든 단계 fetch")
        void profile_정상_full_fetch() {
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.empty());
            given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.HIGH)))
                    .willReturn(Optional.of(new FmpProfile(
                            "AAPL", "Apple Inc.", "TECH",
                            new BigDecimal("3000000000000"),
                            new BigDecimal("0.96"), new BigDecimal("175.0"),
                            "75.60-200.30")));
            // save 시 id 채워서 반환
            given(stockRepository.save(any(Stock.class))).willAnswer(inv -> {
                Stock s = inv.getArgument(0);
                setId(s, 1L);
                return s;
            });

            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(true);
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.HIGH)).willReturn(20);
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(4);

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.ticker()).isEqualTo("AAPL");
            assertThat(result.stockCreated()).isTrue();
            assertThat(result.profileMissing()).isFalse();
            assertThat(result.metaFetched()).isTrue();
            assertThat(result.dailyBarsFetched()).isTrue();
            assertThat(result.earningsFetched()).isTrue();
            assertThat(result.anyFetched()).isTrue();
            // attempt 플래그 — 4단계 모두 진입
            assertThat(result.stockAttempted()).isTrue();
            assertThat(result.metaAttempted()).isTrue();
            assertThat(result.dailyBarsAttempted()).isTrue();
            assertThat(result.earningsAttempted()).isTrue();
            assertThat(result.allFailed()).isFalse();

            // Stock 신규 등록 시 active=true (기본값) + companyName=Apple Inc., sector=TECH
            ArgumentCaptor<Stock> captor = ArgumentCaptor.forClass(Stock.class);
            verify(stockRepository).save(captor.capture());
            Stock saved = captor.getValue();
            assertThat(saved.getTicker()).isEqualTo("AAPL");
            assertThat(saved.getCompanyName()).isEqualTo("Apple Inc.");
            assertThat(saved.getSector()).isEqualTo("TECH");
            assertThat(saved.isActive()).isTrue();
        }

        @Test
        @DisplayName("profile 빈 결과 → placeholder Stock(active=false) + 메타/일봉/어닝 단계 진행")
        void profile_빈_결과_placeholder() {
            given(stockRepository.findByTicker("XYZ")).willReturn(Optional.empty());
            given(fmpClient.fetchProfile(eq("XYZ"), eq(FmpRateLimiter.Priority.HIGH)))
                    .willReturn(Optional.empty());
            given(stockRepository.save(any(Stock.class))).willAnswer(inv -> {
                Stock s = inv.getArgument(0);
                setId(s, 7L);
                return s;
            });

            given(stockMetaRepository.findByStock_Id(7L)).willReturn(Optional.empty());
            // 메타도 빈 응답이라 false 반환
            given(stockMetaSyncService.syncTicker(7L, "XYZ", SyncPriority.HIGH)).willReturn(false);
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(7L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(7L, "XYZ", 30, SyncPriority.HIGH)).willReturn(0);
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(7L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(7L, "XYZ", SyncPriority.HIGH)).willReturn(0);

            LazyFetchResult result = service.ensureExists("XYZ");

            assertThat(result.stockCreated()).isTrue();
            assertThat(result.profileMissing()).isTrue();
            // 메타/일봉/어닝 모두 호출됐지만 빈 응답이라 false
            assertThat(result.metaFetched()).isFalse();
            assertThat(result.dailyBarsFetched()).isFalse();
            assertThat(result.earningsFetched()).isFalse();

            // placeholder Stock 검증: companyName=ticker, sector=null, active=false
            ArgumentCaptor<Stock> captor = ArgumentCaptor.forClass(Stock.class);
            verify(stockRepository).save(captor.capture());
            Stock saved = captor.getValue();
            assertThat(saved.getTicker()).isEqualTo("XYZ");
            assertThat(saved.getCompanyName()).isEqualTo("XYZ");
            assertThat(saved.getSector()).isNull();
            assertThat(saved.isActive()).isFalse();

            // 후속 단계도 호출되었음 — placeholder 이어도 메타/일봉/어닝 시도
            verify(stockMetaSyncService).syncTicker(7L, "XYZ", SyncPriority.HIGH);
            verify(dailyBarSyncService).syncTicker(7L, "XYZ", 30, SyncPriority.HIGH);
            verify(earningsResultSyncService).syncTicker(7L, "XYZ", SyncPriority.HIGH);
        }

        @Test
        @DisplayName("Stock save 자체 throw → 후속 단계 모두 skip, anyFetched=false")
        void stock_save_throw() {
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.empty());
            given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.HIGH)))
                    .willReturn(Optional.of(new FmpProfile(
                            "AAPL", "Apple Inc.", "TECH",
                            null, null, null, null)));
            given(stockRepository.save(any(Stock.class)))
                    .willThrow(new RuntimeException("DataIntegrityViolation"));

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.stockCreated()).isFalse();
            assertThat(result.anyFetched()).isFalse();
            verify(stockMetaSyncService, never()).syncTicker(anyLong(), anyString(), any());
            verify(dailyBarSyncService, never()).syncTicker(anyLong(), anyString(), anyInt(), any());
            verify(earningsResultSyncService, never()).syncTicker(anyLong(), anyString(), any());

            // Stock 등록 시도는 했으나 실패 → allFailed=true
            assertThat(result.stockAttempted()).isTrue();
            assertThat(result.allFailed()).isTrue();
        }
    }

    @Nested
    @DisplayName("Stock 존재 — 단계별 부분 fetch")
    class StockExisting {

        @Test
        @DisplayName("StockMeta 만 없음 → StockMeta 만 fetch, 다른 단계 skip")
        void meta_only() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));

            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(true);

            // DailyBar 1개 이상 존재 → skip
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl)));
            // EarningsResult 1개 이상 존재 → skip
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl)));

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.stockCreated()).isFalse();
            assertThat(result.metaFetched()).isTrue();
            assertThat(result.dailyBarsFetched()).isFalse();
            assertThat(result.earningsFetched()).isFalse();

            verify(stockRepository, never()).save(any());
            verify(dailyBarSyncService, never()).syncTicker(anyLong(), anyString(), anyInt(), any());
            verify(earningsResultSyncService, never()).syncTicker(anyLong(), anyString(), any());
        }

        @Test
        @DisplayName("Stock 존재 + 모두 적재됨 → 아무것도 fetch 안 함")
        void all_skip() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl)));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl)));

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.anyFetched()).isFalse();
            verify(fmpClient, never()).fetchProfile(anyString(), any());
            verify(stockMetaSyncService, never()).syncTicker(anyLong(), anyString(), any());
            verify(dailyBarSyncService, never()).syncTicker(anyLong(), anyString(), anyInt(), any());
            verify(earningsResultSyncService, never()).syncTicker(anyLong(), anyString(), any());
        }

        @Test
        @DisplayName("DailyBar 만 없음 → DailyBar 만 fetch")
        void dailyBars_only() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.HIGH)).willReturn(15);
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of(earningsOf(aapl)));

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.metaFetched()).isFalse();
            assertThat(result.dailyBarsFetched()).isTrue();
            assertThat(result.earningsFetched()).isFalse();
        }

        @Test
        @DisplayName("EarningsResult 만 없음 → EarningsResult 만 fetch")
        void earnings_only() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(metaOf(aapl)));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L))
                    .willReturn(List.of(barOf(aapl)));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(2);

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.metaFetched()).isFalse();
            assertThat(result.dailyBarsFetched()).isFalse();
            assertThat(result.earningsFetched()).isTrue();
        }
    }

    @Nested
    @DisplayName("partial 결과 — 한 단계 throw 격리")
    class PartialResult {

        @Test
        @DisplayName("StockMeta 단계 throw → DailyBar / Earnings 진행, partial result 반환")
        void meta_throw() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));

            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH))
                    .willThrow(new RuntimeException("FMP 5xx"));

            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.HIGH)).willReturn(20);

            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(3);

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.metaFetched()).isFalse();
            assertThat(result.dailyBarsFetched()).isTrue();
            assertThat(result.earningsFetched()).isTrue();
            assertThat(result.anyFetched()).isTrue();

            verify(dailyBarSyncService).syncTicker(1L, "AAPL", 30, SyncPriority.HIGH);
            verify(earningsResultSyncService).syncTicker(1L, "AAPL", SyncPriority.HIGH);
        }

        @Test
        @DisplayName("DailyBar 단계 throw → Meta 정상 / Earnings 진행")
        void dailyBars_throw() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));

            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(true);

            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.HIGH))
                    .willThrow(new RuntimeException("JPA constraint"));

            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(2);

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.metaFetched()).isTrue();
            assertThat(result.dailyBarsFetched()).isFalse();
            assertThat(result.earningsFetched()).isTrue();
        }

        @Test
        @DisplayName("Earnings 단계 throw → Meta / DailyBar 정상")
        void earnings_throw() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));

            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH)).willReturn(true);

            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.HIGH)).willReturn(20);

            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH))
                    .willThrow(new RuntimeException("Finnhub 4xx"));

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.metaFetched()).isTrue();
            assertThat(result.dailyBarsFetched()).isTrue();
            assertThat(result.earningsFetched()).isFalse();
        }
    }

    @Nested
    @DisplayName("allFailed — 모든 시도 실패")
    class AllFailed {

        @Test
        @DisplayName("Stock 미존재 + Stock save throw → allFailed=true (Phase 3 컨트롤러 503 분기)")
        void stock_save_throw_allFailed() {
            given(stockRepository.findByTicker("FAIL")).willReturn(Optional.empty());
            given(fmpClient.fetchProfile(eq("FAIL"), eq(FmpRateLimiter.Priority.HIGH)))
                    .willReturn(Optional.empty());
            given(stockRepository.save(any(Stock.class)))
                    .willThrow(new RuntimeException("DB down"));

            LazyFetchResult result = service.ensureExists("FAIL");

            assertThat(result.allFailed()).isTrue();
            assertThat(result.anyFetched()).isFalse();
            assertThat(result.stockAttempted()).isTrue();
        }

        @Test
        @DisplayName("Stock 미존재 + Stock 신규 등록 + 메타/일봉/어닝 모두 throw → anyFetched=true(stock), allFailed=false")
        void stock_created_but_others_throw() {
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.empty());
            given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.HIGH)))
                    .willReturn(Optional.of(new FmpProfile(
                            "AAPL", "Apple Inc.", "TECH", null, null, null, null)));
            given(stockRepository.save(any(Stock.class))).willAnswer(inv -> {
                Stock s = inv.getArgument(0);
                setId(s, 1L);
                return s;
            });
            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH))
                    .willThrow(new RuntimeException("FMP 5xx"));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.HIGH))
                    .willThrow(new RuntimeException("FMP 5xx"));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH))
                    .willThrow(new RuntimeException("Finnhub 5xx"));

            LazyFetchResult result = service.ensureExists("AAPL");

            // Stock 신규 등록은 성공 → anyFetched=true → allFailed=false
            assertThat(result.stockCreated()).isTrue();
            assertThat(result.anyFetched()).isTrue();
            assertThat(result.allFailed()).isFalse();
            assertThat(result.metaAttempted()).isTrue();
            assertThat(result.dailyBarsAttempted()).isTrue();
            assertThat(result.earningsAttempted()).isTrue();
        }

        @Test
        @DisplayName("Stock 존재 + 메타/일봉/어닝 모두 throw → allFailed=true (Stock 시도 안 함)")
        void stock_existing_others_all_throw() {
            Stock aapl = stockOf(1L, "AAPL");
            given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));

            given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());
            given(stockMetaSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH))
                    .willThrow(new RuntimeException("FMP 5xx"));
            given(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(1L)).willReturn(List.of());
            given(dailyBarSyncService.syncTicker(1L, "AAPL", 30, SyncPriority.HIGH))
                    .willThrow(new RuntimeException("FMP 5xx"));
            given(earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(1L))
                    .willReturn(List.of());
            given(earningsResultSyncService.syncTicker(1L, "AAPL", SyncPriority.HIGH))
                    .willThrow(new RuntimeException("Finnhub 5xx"));

            LazyFetchResult result = service.ensureExists("AAPL");

            assertThat(result.stockCreated()).isFalse();
            assertThat(result.stockAttempted()).isFalse();
            assertThat(result.metaAttempted()).isTrue();
            assertThat(result.dailyBarsAttempted()).isTrue();
            assertThat(result.earningsAttempted()).isTrue();
            assertThat(result.anyFetched()).isFalse();
            assertThat(result.allFailed()).isTrue();
        }
    }

    // ─────────── helpers ───────────

    private static Stock stockOf(Long id, String ticker) {
        Stock s = Stock.builder().ticker(ticker).companyName("Co").sector("TECH").build();
        setId(s, id);
        return s;
    }

    private static StockMeta metaOf(Stock stock) {
        return StockMeta.builder()
                .stock(stock)
                .marketCapUsd(BigDecimal.ONE)
                .build();
    }

    private static DailyBar barOf(Stock stock) {
        return DailyBar.builder()
                .stock(stock)
                .barDate(java.time.LocalDate.parse("2026-04-30"))
                .closePrice(BigDecimal.ONE)
                .volume(1L)
                .build();
    }

    private static EarningsResult earningsOf(Stock stock) {
        return EarningsResult.builder()
                .stock(stock)
                .announcedAt(java.time.Instant.parse("2026-04-30T13:00:00Z"))
                .fiscalPeriodLabel("Q1 FY26")
                .build();
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
