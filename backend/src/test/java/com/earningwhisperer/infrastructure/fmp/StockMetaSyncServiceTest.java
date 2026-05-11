package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockMeta;
import com.earningwhisperer.domain.stock.StockMetaRepository;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
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
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * {@link StockMetaSyncService} 단위 테스트.
 *
 * <p>FmpClient / Repository mock — 외부 호출 / DB 미접근.
 * 검증 포인트:
 * <ul>
 *     <li>profile 빈 응답 → {@code false} 반환, 영속화 미진입</li>
 *     <li>기존 StockMeta → updateMeta, save 호출 없음</li>
 *     <li>신규 StockMeta → builder 로 save</li>
 *     <li>Stock 미존재 → {@code false} 반환</li>
 *     <li>dividendYield 계산 (정상 / null / price=0 / 한도 초과)</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("StockMetaSyncService 단위 테스트")
class StockMetaSyncServiceTest {

    @Mock private FmpClient fmpClient;
    @Mock private StockRepository stockRepository;
    @Mock private StockMetaRepository stockMetaRepository;

    @InjectMocks
    private StockMetaSyncService service;

    private Stock aapl;

    @BeforeEach
    void setUp() {
        aapl = stockOf(1L, "AAPL", "Apple Inc.");
    }

    @Test
    @DisplayName("신규 StockMeta — builder 로 save 후 true 반환")
    void 신규_StockMeta_save() {
        given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(Optional.of(profileOf("AAPL", "175.0", "0.96", "75.60-200.30", "3000000000000")));
        given(stockRepository.findById(1L)).willReturn(Optional.of(aapl));
        given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());

        boolean result = service.syncTicker(1L, "AAPL", SyncPriority.LOW);

        assertThat(result).isTrue();
        ArgumentCaptor<StockMeta> captor = ArgumentCaptor.forClass(StockMeta.class);
        verify(stockMetaRepository).save(captor.capture());
        StockMeta saved = captor.getValue();
        assertThat(saved.getStock()).isEqualTo(aapl);
        assertThat(saved.getMarketCapUsd()).isEqualByComparingTo("3000000000000");
        assertThat(saved.getHigh52w()).isEqualByComparingTo("200.30");
        assertThat(saved.getLow52w()).isEqualByComparingTo("75.60");
        // 0.96 / 175.0 = 0.005485714... → HALF_UP 6자리
        assertThat(saved.getDividendYield()).isEqualByComparingTo("0.005486");
    }

    @Test
    @DisplayName("기존 StockMeta — updateMeta 호출, save 호출 없음, true 반환")
    void 기존_StockMeta_update() {
        StockMeta existing = StockMeta.builder()
                .stock(aapl)
                .marketCapUsd(new BigDecimal("1000"))
                .build();

        given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(Optional.of(profileOf("AAPL", "100.0", "1.00", "50.00-150.00", "999")));
        given(stockRepository.findById(1L)).willReturn(Optional.of(aapl));
        given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.of(existing));

        boolean result = service.syncTicker(1L, "AAPL", SyncPriority.LOW);

        assertThat(result).isTrue();
        verify(stockMetaRepository, never()).save(any(StockMeta.class));
        assertThat(existing.getMarketCapUsd()).isEqualByComparingTo("999");
        assertThat(existing.getHigh52w()).isEqualByComparingTo("150.00");
        assertThat(existing.getLow52w()).isEqualByComparingTo("50.00");
        assertThat(existing.getDividendYield()).isEqualByComparingTo("0.010000");
    }

    @Test
    @DisplayName("profile 빈 응답 → false 반환, 영속화 미진입")
    void profile_empty_false() {
        given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(Optional.empty());

        boolean result = service.syncTicker(1L, "AAPL", SyncPriority.LOW);

        assertThat(result).isFalse();
        verify(stockRepository, never()).findById(any());
        verify(stockMetaRepository, never()).save(any(StockMeta.class));
    }

    @Test
    @DisplayName("Stock 미존재(stockId / ticker 둘 다 못 찾음) → false 반환, save 없음")
    void stock_미존재_false() {
        given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(Optional.of(profileOf("AAPL", "100.0", "1.00", "50.00-150.00", "999")));
        given(stockRepository.findById(1L)).willReturn(Optional.empty());
        given(stockRepository.findByTicker("AAPL")).willReturn(Optional.empty());

        boolean result = service.syncTicker(1L, "AAPL", SyncPriority.LOW);

        assertThat(result).isFalse();
        verify(stockMetaRepository, never()).save(any(StockMeta.class));
    }

    @Test
    @DisplayName("stockId 미존재여도 ticker fallback 으로 reattach → true 반환")
    void ticker_fallback_reattach() {
        given(fmpClient.fetchProfile(eq("AAPL"), eq(FmpRateLimiter.Priority.LOW)))
                .willReturn(Optional.of(profileOf("AAPL", "100.0", "1.00", "50.00-150.00", "999")));
        given(stockRepository.findById(99L)).willReturn(Optional.empty());
        given(stockRepository.findByTicker("AAPL")).willReturn(Optional.of(aapl));
        given(stockMetaRepository.findByStock_Id(1L)).willReturn(Optional.empty());

        boolean result = service.syncTicker(99L, "AAPL", SyncPriority.LOW);

        assertThat(result).isTrue();
        verify(stockMetaRepository).save(any(StockMeta.class));
    }

    @Test
    @DisplayName("dividendYield 계산: price=null 이면 null")
    void dividendYield_price_null() {
        assertThat(StockMetaSyncService.computeDividendYield(new BigDecimal("1.00"), null, "AAPL"))
                .isNull();
    }

    @Test
    @DisplayName("dividendYield 계산: lastDiv=null 이면 null")
    void dividendYield_lastDiv_null() {
        assertThat(StockMetaSyncService.computeDividendYield(null, new BigDecimal("100"), "AAPL"))
                .isNull();
    }

    @Test
    @DisplayName("dividendYield 계산: price=0 이면 null (분모 invalid)")
    void dividendYield_price_zero() {
        assertThat(StockMetaSyncService.computeDividendYield(
                new BigDecimal("1.00"), BigDecimal.ZERO, "AAPL")).isNull();
    }

    @Test
    @DisplayName("dividendYield 계산: 정상 케이스 6자리 소수")
    void dividendYield_정상() {
        BigDecimal yield = StockMetaSyncService.computeDividendYield(
                new BigDecimal("0.96"), new BigDecimal("175.0"), "AAPL");
        assertThat(yield).isEqualByComparingTo("0.005486");
    }

    @Test
    @DisplayName("dividendYield 계산: yield ≥ 100 이면 null (DECIMAL(8,6) 한도 초과)")
    void dividendYield_한도_초과() {
        // lastDiv=10, price=0.05 → yield = 200 → null
        BigDecimal yield = StockMetaSyncService.computeDividendYield(
                new BigDecimal("10"), new BigDecimal("0.05"), "BUG");
        assertThat(yield).isNull();
    }

    @Test
    @DisplayName("dividendYield 계산: yield 가 정확히 100 이면 null (≥ 비교)")
    void dividendYield_정확히_100() {
        BigDecimal yield = StockMetaSyncService.computeDividendYield(
                new BigDecimal("100"), new BigDecimal("1"), "BUG");
        assertThat(yield).isNull();
    }

    @Test
    @DisplayName("dividendYield 계산: yield 가 99.999999 (한도 직전) 이면 정상 반환")
    void dividendYield_한도_직전() {
        // lastDiv=99.999999, price=1 → yield = 99.999999 → 정상
        BigDecimal yield = StockMetaSyncService.computeDividendYield(
                new BigDecimal("99.999999"), new BigDecimal("1"), "EDGE");
        assertThat(yield).isEqualByComparingTo("99.999999");
    }

    // ─────────── helpers ───────────

    private static Stock stockOf(Long id, String ticker, String name) {
        Stock s = Stock.builder().ticker(ticker).companyName(name).sector("TECH").build();
        setId(s, id);
        return s;
    }

    private static FmpProfile profileOf(String symbol,
                                        String price,
                                        String lastDividend,
                                        String range,
                                        String marketCap) {
        return new FmpProfile(
                symbol,
                "test",
                "TECH",
                marketCap == null ? null : new BigDecimal(marketCap),
                lastDividend == null ? null : new BigDecimal(lastDividend),
                price == null ? null : new BigDecimal(price),
                range
        );
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
