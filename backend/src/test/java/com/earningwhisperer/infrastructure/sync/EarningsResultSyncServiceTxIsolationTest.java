package com.earningwhisperer.infrastructure.sync;

import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.finnhub.EarningsResultSyncService;
import com.earningwhisperer.infrastructure.finnhub.FinnhubClient;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubEarningsRow;
import com.earningwhisperer.infrastructure.fmp.FmpClient;
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
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;

/**
 * {@link EarningsResultSyncService} 의 ticker 단위 {@code @Transactional} 격리 통합 테스트.
 *
 * <p>{@link StockMetaSyncServiceTxIsolationTest} 와 동일한 검증 가설:
 * 한 ticker 의 PersistenceException 이 다른 ticker 의 commit 을 silent rollback 시키지 않는다.
 *
 * <p>PersistenceException trigger: {@code epsActual} 컬럼 {@code DECIMAL(10,4)} 정수부 6자리
 * 한도 → 7자리 mock 응답으로 numeric overflow.
 *
 * <p>구성: ticker A 의 응답에 정상 row + overflow row 를 섞어 부분 success → 전체 rollback 시나리오
 * 재현. ticker B 는 정상 응답.
 */
@SpringBootTest(
        classes = SyncServiceTxIsolationTestConfig.class,
        properties = {
                "spring.datasource.url=jdbc:h2:mem:tx_isolation_earnings;MODE=MySQL;DB_CLOSE_DELAY=-1",
                "spring.datasource.driver-class-name=org.h2.Driver",
                "spring.datasource.username=sa",
                "spring.datasource.password=",
                "spring.jpa.hibernate.ddl-auto=create-drop",
                "spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.H2Dialect"
        }
)
@DisplayName("EarningsResultSyncService 트랜잭션 격리 통합 테스트")
class EarningsResultSyncServiceTxIsolationTest {

    @Autowired private EarningsResultSyncService service;
    @Autowired private StockRepository stockRepository;
    @Autowired private EarningsResultRepository earningsResultRepository;
    @Autowired private TransactionTemplate transactionTemplate;

    @MockBean private FmpClient fmpClient;
    @MockBean private FinnhubClient finnhubClient;

    private Long stockIdA;
    private Long stockIdB;

    @BeforeEach
    void setUp() {
        earningsResultRepository.deleteAllInBatch();
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
    @DisplayName("S1: 정상 응답 시 syncTicker 가 row 들을 다른 트랜잭션에서 조회 가능하도록 commit 한다")
    void s1_정상_ticker_commit_성공() {
        given(finnhubClient.fetchEarningsHistory(eq("AAA"), any())).willReturn(List.of(
                new FinnhubEarningsRow("AAA", LocalDate.of(2026, 3, 31),
                        new BigDecimal("1.50"), new BigDecimal("1.30"),
                        new BigDecimal("0.20"), new BigDecimal("15.3846"), 1)
        ));

        int inserted = service.syncTicker(stockIdA, "AAA", SyncPriority.LOW);

        assertThat(inserted).isEqualTo(1);
        List<EarningsResult> rows = readInNewTx(() ->
                earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockIdA));
        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).getEpsActual()).isEqualByComparingTo("1.50");
        assertThat(rows.get(0).getFiscalPeriodLabel()).isEqualTo("Q1 FY26");
    }

    // ─────────────────── S2. ★ 핵심: ticker A 실패 시 ticker B commit 보존 ───────────────────

    @Test
    @DisplayName("S2: ticker A 의 한 row 가 overflow 로 실패해도 ticker B 의 commit 은 보존된다 (★ 핵심)")
    void s2_ticker_A_persistenceException_시_ticker_B_commit_보존() {
        // ticker A: 첫 row 정상, 두 번째 row 의 epsActual 이 정수부 7자리 → DECIMAL(10,4) overflow
        //          → service.syncTicker 가 propagate. 정상 row 도 ticker A 트랜잭션과 함께 rollback.
        given(finnhubClient.fetchEarningsHistory(eq("AAA"), any())).willReturn(List.of(
                new FinnhubEarningsRow("AAA", LocalDate.of(2026, 3, 31),
                        new BigDecimal("1.50"), new BigDecimal("1.30"),
                        new BigDecimal("0.20"), new BigDecimal("15.3846"), 1),
                new FinnhubEarningsRow("AAA", LocalDate.of(2025, 12, 31),
                        new BigDecimal("1234567.0000"), // 정수부 7자리 — overflow
                        new BigDecimal("1.00"),
                        new BigDecimal("0.10"), new BigDecimal("10.0000"), 4)
        ));
        // ticker B: 정상 1건
        given(finnhubClient.fetchEarningsHistory(eq("BBB"), any())).willReturn(List.of(
                new FinnhubEarningsRow("BBB", LocalDate.of(2026, 3, 31),
                        new BigDecimal("2.50"), new BigDecimal("2.30"),
                        new BigDecimal("0.20"), new BigDecimal("8.6957"), 1)
        ));

        List<String> failed = new ArrayList<>();
        for (String ticker : List.of("AAA", "BBB")) {
            Long stockId = ticker.equals("AAA") ? stockIdA : stockIdB;
            try {
                service.syncTicker(stockId, ticker, SyncPriority.LOW);
            } catch (RuntimeException e) {
                failed.add(ticker);
            }
        }

        assertThat(failed).containsExactly("AAA");

        // 검증 1 — ticker A 의 정상 row 도 rollback 되어 영속화되지 않았다.
        List<EarningsResult> rowsA = readInNewTx(() ->
                earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockIdA));
        assertThat(rowsA).as("ticker A 트랜잭션 전체가 rollback 되어야 부분 데이터 누수 없음").isEmpty();

        // 검증 2 — ★ ticker B 는 영향 없이 commit.
        List<EarningsResult> rowsB = readInNewTx(() ->
                earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockIdB));
        assertThat(rowsB).as("ticker B 의 commit 은 ticker A 의 rollback 과 격리되어야 함").hasSize(1);
        assertThat(rowsB.get(0).getEpsActual()).isEqualByComparingTo("2.50");
    }

    // ─────────────────── S3. 외부 client 가 RuntimeException → 격리 + propagate ───────────────────

    @Test
    @DisplayName("S3: 외부 client RuntimeException 도 ticker 단위로 격리되며 propagate 된다")
    void s3_client_RuntimeException_시_다른_ticker_영향_없음() {
        given(finnhubClient.fetchEarningsHistory(eq("AAA"), any()))
                .willThrow(new RuntimeException("simulated upstream failure"));
        given(finnhubClient.fetchEarningsHistory(eq("BBB"), any())).willReturn(List.of(
                new FinnhubEarningsRow("BBB", LocalDate.of(2026, 3, 31),
                        new BigDecimal("2.50"), new BigDecimal("2.30"),
                        new BigDecimal("0.20"), new BigDecimal("8.6957"), 1)
        ));

        List<String> failed = new ArrayList<>();
        for (String ticker : List.of("AAA", "BBB")) {
            Long stockId = ticker.equals("AAA") ? stockIdA : stockIdB;
            try {
                service.syncTicker(stockId, ticker, SyncPriority.LOW);
            } catch (RuntimeException e) {
                failed.add(ticker);
            }
        }

        assertThat(failed).containsExactly("AAA");
        assertThat(readInNewTx(() ->
                earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockIdA)))
                .as("ticker A 는 영속화 미진입").isEmpty();
        assertThat(readInNewTx(() ->
                earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockIdB)))
                .as("ticker B 의 commit 은 보존").hasSize(1);
    }

    // ─────────────────────────── helpers ───────────────────────────

    private <T> T readInNewTx(java.util.function.Supplier<T> action) {
        return transactionTemplate.execute(status -> action.get());
    }
}
