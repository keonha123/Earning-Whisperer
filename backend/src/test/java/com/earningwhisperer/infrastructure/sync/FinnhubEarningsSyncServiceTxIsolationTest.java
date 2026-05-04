package com.earningwhisperer.infrastructure.sync;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.infrastructure.finnhub.FinnhubClient;
import com.earningwhisperer.infrastructure.finnhub.FinnhubEarningsSyncService;
import com.earningwhisperer.infrastructure.fmp.FmpClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link FinnhubEarningsSyncService} 의 row 단위 {@code @Transactional} 격리 통합 테스트.
 *
 * <p>{@link StockMetaSyncServiceTxIsolationTest} / {@link EarningsResultSyncServiceTxIsolationTest}
 * 와 동일 검증 가설: 한 row 의 PersistenceException 이 다른 row 의 commit 을 silent rollback 시키지
 * 않는다. 본 service 는 ticker 단위가 아닌 (ticker × scheduledAt) 단위 — Finnhub
 * {@code /calendar/earnings} 응답이 미리 ticker 별 row 로 펼쳐져 있기 때문이다.
 *
 * <p>PersistenceException trigger: {@code epsEstimate} 컬럼 {@code DECIMAL(10,4)} 정수부 6자리
 * 한도 → 7자리 mock estimate 로 numeric overflow.
 *
 * <p>구성: 3개 ticker 중 ticker B 의 row 만 epsEstimate overflow → A/C 의 commit 이 보존되는지 검증.
 * Scheduler 의 try/catch 흉내를 본 테스트가 직접 수행한다 (per-row try/catch 격리 가설 검증).
 */
@SpringBootTest(
        classes = SyncServiceTxIsolationTestConfig.class,
        properties = {
                "spring.datasource.url=jdbc:h2:mem:tx_isolation_finnhub_calendar;MODE=MySQL;DB_CLOSE_DELAY=-1",
                "spring.datasource.driver-class-name=org.h2.Driver",
                "spring.datasource.username=sa",
                "spring.datasource.password=",
                "spring.jpa.hibernate.ddl-auto=create-drop",
                "spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.H2Dialect"
        }
)
@DisplayName("FinnhubEarningsSyncService 트랜잭션 격리 통합 테스트")
class FinnhubEarningsSyncServiceTxIsolationTest {

    @Autowired private FinnhubEarningsSyncService service;
    @Autowired private StockRepository stockRepository;
    @Autowired private EarningsCalendarRepository earningsCalendarRepository;
    @Autowired private TransactionTemplate transactionTemplate;

    // FmpClient / FinnhubClient 는 본 테스트가 직접 사용하지 않지만, config 가 다른 sync service 들을
    // 함께 등록하므로 의존성 충족용 mock 등록.
    @MockBean private FmpClient fmpClient;
    @MockBean private FinnhubClient finnhubClient;

    private final Instant scheduledAt = LocalDate.of(2026, 5, 15)
            .atStartOfDay(ZoneOffset.UTC).toInstant();

    @BeforeEach
    void setUp() {
        // 매 테스트마다 데이터 정리. 본 테스트는 트랜잭션 NOT 적용이므로 자동 롤백 없음 → 명시적 wipe.
        earningsCalendarRepository.deleteAllInBatch();
        stockRepository.deleteAllInBatch();

        // setUp 도 트랜잭션 외 영역 — save 가 즉시 commit. 의도된 동작.
        stockRepository.save(Stock.builder()
                .ticker("AAA").companyName("Alpha").sector("TECH").build());
        stockRepository.save(Stock.builder()
                .ticker("BBB").companyName("Bravo").sector("TECH").build());
        stockRepository.save(Stock.builder()
                .ticker("CCC").companyName("Charlie").sector("TECH").build());
    }

    // ───────────────────────────── S1. 정상 row 단독 → commit ─────────────────────────────

    @Test
    @DisplayName("S1: 정상 응답 시 upsertRow 가 다른 트랜잭션에서 조회 가능하도록 commit 한다")
    void s1_정상_row_commit_성공() {
        FinnhubEarningsSyncService.UpsertResult result = service.upsertRow(
                "AAA", scheduledAt, true,
                new BigDecimal("1.55"), new BigDecimal("90000000000"));

        assertThat(result).isEqualTo(FinnhubEarningsSyncService.UpsertResult.INSERTED);
        Optional<EarningsCalendar> persisted = readInNewTx(() ->
                earningsCalendarRepository.findByStockTickerAndScheduledAt("AAA", scheduledAt));
        assertThat(persisted).isPresent();
        assertThat(persisted.get().getEpsEstimate()).isEqualByComparingTo("1.55");
        assertThat(persisted.get().getRevenueEstimate()).isEqualByComparingTo("90000000000");
        assertThat(persisted.get().isConfirmed()).isTrue();
    }

    // ─────────────── S2. ★ 핵심: row B 실패 시 row A / row C commit 보존 ───────────────

    @Test
    @DisplayName("S2: row B 가 epsEstimate overflow 로 실패해도 row A / row C 의 commit 은 보존된다 (★ 핵심)")
    void s2_row_B_persistenceException_시_row_A_C_commit_보존() {
        // 3개 ticker — A 정상, B overflow, C 정상.
        // epsEstimate 컬럼 DECIMAL(10,4) 정수부 6자리 한도 — 7자리 값이면 commit 시점에 DataException.
        record Row(String ticker, BigDecimal eps, BigDecimal rev) {}
        List<Row> rows = List.of(
                new Row("AAA", new BigDecimal("1.55"), new BigDecimal("90000000000")),
                new Row("BBB", new BigDecimal("1234567.0000"), new BigDecimal("80000000000")), // overflow
                new Row("CCC", new BigDecimal("3.20"), new BigDecimal("70000000000"))
        );

        // Scheduler 의 per-row try/catch 흉내.
        List<String> failed = new ArrayList<>();
        for (Row row : rows) {
            try {
                service.upsertRow(row.ticker(), scheduledAt, true, row.eps(), row.rev());
            } catch (RuntimeException e) {
                failed.add(row.ticker());
            }
        }

        // row B 만 실패.
        assertThat(failed).containsExactly("BBB");

        // 검증 1 — row A 는 영향 없이 commit.
        Optional<EarningsCalendar> rowA = readInNewTx(() ->
                earningsCalendarRepository.findByStockTickerAndScheduledAt("AAA", scheduledAt));
        assertThat(rowA).as("row A 는 row B 의 rollback 과 격리되어야 함").isPresent();
        assertThat(rowA.get().getEpsEstimate()).isEqualByComparingTo("1.55");

        // 검증 2 — row B 는 rollback 되어 영속화 안됨.
        Optional<EarningsCalendar> rowB = readInNewTx(() ->
                earningsCalendarRepository.findByStockTickerAndScheduledAt("BBB", scheduledAt));
        assertThat(rowB).as("row B 트랜잭션은 rollback 되어 영속화되지 않아야 함").isEmpty();

        // 검증 3 — ★ row C 도 row B 의 실패와 무관하게 commit (실패 이후 row 처리 진행).
        Optional<EarningsCalendar> rowC = readInNewTx(() ->
                earningsCalendarRepository.findByStockTickerAndScheduledAt("CCC", scheduledAt));
        assertThat(rowC).as("row C 의 commit 은 row B 의 rollback 이후에도 보존되어야 함").isPresent();
        assertThat(rowC.get().getEpsEstimate()).isEqualByComparingTo("3.20");
    }

    // ─────────────── S3. Stock 미존재 row 는 SKIPPED — 다른 row 의 commit 영향 없음 ───────────────

    @Test
    @DisplayName("S3: Stock 미존재 ticker 는 SKIPPED 반환 + 다른 row 의 commit 보존")
    void s3_stock_미존재_skip_시_다른_row_영향_없음() {
        // 등록되지 않은 ticker "ZZZ" → upsertRow 가 SKIPPED 반환.
        FinnhubEarningsSyncService.UpsertResult skipped = service.upsertRow(
                "ZZZ", scheduledAt, true, new BigDecimal("1.00"), new BigDecimal("1000"));
        assertThat(skipped).isEqualTo(FinnhubEarningsSyncService.UpsertResult.SKIPPED);

        // 등록된 ticker "AAA" 는 정상 commit.
        FinnhubEarningsSyncService.UpsertResult inserted = service.upsertRow(
                "AAA", scheduledAt, true, new BigDecimal("2.00"), new BigDecimal("2000"));
        assertThat(inserted).isEqualTo(FinnhubEarningsSyncService.UpsertResult.INSERTED);

        // 검증 — SKIPPED row 는 영속화 미진입, 정상 row 만 commit.
        assertThat(readInNewTx(() ->
                earningsCalendarRepository.findByStockTickerAndScheduledAt("ZZZ", scheduledAt)))
                .as("Stock 미존재 ticker 는 영속화 미진입").isEmpty();
        assertThat(readInNewTx(() ->
                earningsCalendarRepository.findByStockTickerAndScheduledAt("AAA", scheduledAt)))
                .as("정상 ticker 의 commit 은 보존").isPresent();
    }

    // ─────────────────────────── helpers ───────────────────────────

    private <T> T readInNewTx(java.util.function.Supplier<T> action) {
        return transactionTemplate.execute(status -> action.get());
    }
}
