package com.earningwhisperer.infrastructure.sync;

import com.earningwhisperer.domain.stock.DailyBar;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.finnhub.FinnhubClient;
import com.earningwhisperer.infrastructure.fmp.DailyBarSyncService;
import com.earningwhisperer.infrastructure.fmp.FmpClient;
import com.earningwhisperer.infrastructure.fmp.dto.FmpHistoricalBar;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;

/**
 * {@link DailyBarSyncService} 의 ticker 단위 {@code @Transactional} 격리 통합 테스트.
 *
 * <p>{@link StockMetaSyncServiceTxIsolationTest} 와 동일한 검증 가설:
 * 한 ticker 의 PersistenceException 이 다른 ticker 의 commit 을 silent rollback 시키지 않는다.
 *
 * <p>PersistenceException trigger: {@code closePrice} 컬럼 {@code DECIMAL(12,4)} 정수부 8자리
 * 한도 → 9자리 mock bar 응답으로 numeric overflow.
 *
 * <p>중요: ticker A 의 응답에 정상 bar 1개 + overflow bar 1개 를 섞어, service 가 정상 bar 를
 * 먼저 처리(persistence context 에 stage)한 뒤 두 번째 bar 에서 commit 시 overflow 로 실패하는
 * 시나리오를 재현한다 — 이래야 "한 ticker 내 부분 success → ticker 단위 commit 시 rollback"
 * 동작이 정확히 검증된다.
 */
@SpringBootTest(
        classes = SyncServiceTxIsolationTestConfig.class,
        properties = {
                "spring.datasource.url=jdbc:h2:mem:tx_isolation_dailybar;MODE=MySQL;DB_CLOSE_DELAY=-1",
                "spring.datasource.driver-class-name=org.h2.Driver",
                "spring.datasource.username=sa",
                "spring.datasource.password=",
                "spring.jpa.hibernate.ddl-auto=create-drop",
                "spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.H2Dialect"
        }
)
@DisplayName("DailyBarSyncService 트랜잭션 격리 통합 테스트")
class DailyBarSyncServiceTxIsolationTest {

    @Autowired private DailyBarSyncService service;
    @Autowired private StockRepository stockRepository;
    @Autowired private DailyBarRepository dailyBarRepository;
    @Autowired private TransactionTemplate transactionTemplate;

    @MockBean private FmpClient fmpClient;
    @MockBean private FinnhubClient finnhubClient;

    private Long stockIdA;
    private Long stockIdB;

    @BeforeEach
    void setUp() {
        dailyBarRepository.deleteAllInBatch();
        stockRepository.deleteAllInBatch();

        Stock a = stockRepository.save(Stock.builder()
                .ticker("AAA").companyName("Alpha").sector("TECH").build());
        Stock b = stockRepository.save(Stock.builder()
                .ticker("BBB").companyName("Bravo").sector("TECH").build());
        stockIdA = a.getId();
        stockIdB = b.getId();
    }

    // ───────────────────────────── S1. 정상 ticker 단독 → commit ─────────────────────────────

    @Test
    @DisplayName("S1: 정상 응답 시 syncTicker 가 모든 bar 를 다른 트랜잭션에서 조회 가능하도록 commit 한다")
    void s1_정상_ticker_commit_성공() {
        given(fmpClient.fetchHistorical(eq("AAA"), anyInt(), any())).willReturn(List.of(
                new FmpHistoricalBar(LocalDate.of(2026, 5, 1), new BigDecimal("100.00"), 1_000_000L),
                new FmpHistoricalBar(LocalDate.of(2026, 4, 30), new BigDecimal("99.50"), 900_000L)
        ));

        int processed = service.syncTicker(stockIdA, "AAA", 30, SyncPriority.LOW);

        assertThat(processed).isEqualTo(2);
        List<DailyBar> bars = readInNewTx(() ->
                dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(stockIdA));
        assertThat(bars).hasSize(2);
        assertThat(bars.get(0).getBarDate()).isEqualTo(LocalDate.of(2026, 5, 1));
        assertThat(bars.get(0).getClosePrice()).isEqualByComparingTo("100.00");
    }

    // ─────────────────── S2. ★ 핵심: ticker A 실패 시 ticker B commit 보존 ───────────────────

    @Test
    @DisplayName("S2: ticker A 의 한 bar 가 overflow 로 실패해도 ticker B 의 commit 은 보존된다 (★ 핵심)")
    void s2_ticker_A_persistenceException_시_ticker_B_commit_보존() {
        // ticker A: 첫 bar 는 정상, 두 번째 bar 의 closePrice 가 정수부 9자리 → DECIMAL(12,4) overflow
        //          → service.syncTicker 가 propagate 하는 예외 + 첫 정상 bar 도 ticker A 트랜잭션과
        //            함께 rollback 되어야 한다.
        given(fmpClient.fetchHistorical(eq("AAA"), anyInt(), any())).willReturn(List.of(
                new FmpHistoricalBar(LocalDate.of(2026, 5, 1), new BigDecimal("100.00"), 1_000_000L),
                new FmpHistoricalBar(LocalDate.of(2026, 4, 30),
                        new BigDecimal("123456789.0000"), // 정수부 9자리 — overflow
                        900_000L)
        ));
        // ticker B: 정상
        given(fmpClient.fetchHistorical(eq("BBB"), anyInt(), any())).willReturn(List.of(
                new FmpHistoricalBar(LocalDate.of(2026, 5, 1), new BigDecimal("200.00"), 2_000_000L),
                new FmpHistoricalBar(LocalDate.of(2026, 4, 30), new BigDecimal("199.50"), 1_800_000L)
        ));

        List<String> failed = new ArrayList<>();
        for (String ticker : List.of("AAA", "BBB")) {
            Long stockId = ticker.equals("AAA") ? stockIdA : stockIdB;
            try {
                service.syncTicker(stockId, ticker, 30, SyncPriority.LOW);
            } catch (RuntimeException e) {
                failed.add(ticker);
            }
        }

        assertThat(failed).containsExactly("AAA");

        // 검증 1 — ticker A 의 모든 bar (정상 1개 포함) 가 rollback. 부분 commit 금지.
        List<DailyBar> barsA = readInNewTx(() ->
                dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(stockIdA));
        assertThat(barsA).as("ticker A 트랜잭션 전체가 rollback 되어야 부분 데이터 누수 없음").isEmpty();

        // 검증 2 — ★ ticker B 는 영향 없이 commit.
        List<DailyBar> barsB = readInNewTx(() ->
                dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(stockIdB));
        assertThat(barsB).as("ticker B 의 commit 은 ticker A 의 rollback 과 격리되어야 함").hasSize(2);
        assertThat(barsB.get(0).getClosePrice()).isEqualByComparingTo("200.00");
    }

    // ─────────────────── S3. 외부 client 가 RuntimeException → 격리 + propagate ───────────────────

    @Test
    @DisplayName("S3: 외부 client RuntimeException 도 ticker 단위로 격리되며 propagate 된다")
    void s3_client_RuntimeException_시_다른_ticker_영향_없음() {
        given(fmpClient.fetchHistorical(eq("AAA"), anyInt(), any()))
                .willThrow(new RuntimeException("simulated upstream failure"));
        given(fmpClient.fetchHistorical(eq("BBB"), anyInt(), any())).willReturn(List.of(
                new FmpHistoricalBar(LocalDate.of(2026, 5, 1), new BigDecimal("200.00"), 2_000_000L)
        ));

        List<String> failed = new ArrayList<>();
        for (String ticker : List.of("AAA", "BBB")) {
            Long stockId = ticker.equals("AAA") ? stockIdA : stockIdB;
            try {
                service.syncTicker(stockId, ticker, 30, SyncPriority.LOW);
            } catch (RuntimeException e) {
                failed.add(ticker);
            }
        }

        assertThat(failed).containsExactly("AAA");
        assertThat(readInNewTx(() ->
                dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(stockIdA)))
                .as("ticker A 는 영속화 미진입").isEmpty();
        assertThat(readInNewTx(() ->
                dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(stockIdB)))
                .as("ticker B 의 commit 은 보존").hasSize(1);
    }

    // ─────────────────────────── helpers ───────────────────────────

    private <T> T readInNewTx(java.util.function.Supplier<T> action) {
        return transactionTemplate.execute(status -> action.get());
    }
}
