package com.earningwhisperer.infrastructure.sync;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockMeta;
import com.earningwhisperer.domain.stock.StockMetaRepository;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.finnhub.FinnhubClient;
import com.earningwhisperer.infrastructure.fmp.FmpClient;
import com.earningwhisperer.infrastructure.fmp.StockMetaSyncService;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;

/**
 * {@link StockMetaSyncService} 의 ticker 단위 {@code @Transactional} 격리 통합 테스트.
 *
 * <p>Phase 2-B 의 silent-failure-hunter BLOCKING 지적 대응 — 단위 테스트는 Service mock 으로
 * 우회되었으므로 본 통합 테스트가 회귀 방어선 역할을 한다.
 *
 * <p>검증 가설: 한 ticker 의 PersistenceException 이 발생해도 Spring 은 그 ticker 의
 * 트랜잭션만 rollback 하고, 별도 트랜잭션으로 처리된 다른 ticker 의 commit 은 보존된다.
 *
 * <p>구현 메모:
 * <ul>
 *     <li>{@code @SpringBootTest(classes = SyncServiceTxIsolationTestConfig.class)} — minimal
 *         Spring 부팅. 실제 AOP 프록시 + {@code @Transactional} 동작 그대로.</li>
 *     <li>테스트 메서드는 {@code @Transactional} 미적용 — service 내부 트랜잭션을 검증해야 하므로
 *         바깥에서 트랜잭션을 감싸면 안 된다.</li>
 *     <li>외부 API 는 {@code @MockBean FmpClient} / {@code @MockBean FinnhubClient} 로 우회.
 *         {@link SyncServiceTxIsolationTestConfig} 가 3개 Service 를 모두 등록하므로 본 테스트가
 *         직접 사용하지 않는 FinnhubClient 도 의존성 충족용으로 mock 등록한다.</li>
 *     <li>PersistenceException trigger: {@code marketCap} 컬럼 {@code DECIMAL(20,2)} 정수부
 *         18자리 한도 → 19자리 mock 응답으로 자연스러운 numeric overflow.</li>
 * </ul>
 */
@SpringBootTest(
        classes = SyncServiceTxIsolationTestConfig.class,
        properties = {
                "spring.datasource.url=jdbc:h2:mem:tx_isolation_meta;MODE=MySQL;DB_CLOSE_DELAY=-1",
                "spring.datasource.driver-class-name=org.h2.Driver",
                "spring.datasource.username=sa",
                "spring.datasource.password=",
                "spring.jpa.hibernate.ddl-auto=create-drop",
                "spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.H2Dialect"
        }
)
@DisplayName("StockMetaSyncService 트랜잭션 격리 통합 테스트")
class StockMetaSyncServiceTxIsolationTest {

    @Autowired private StockMetaSyncService service;
    @Autowired private StockRepository stockRepository;
    @Autowired private StockMetaRepository stockMetaRepository;
    @Autowired private TransactionTemplate transactionTemplate;

    @MockBean private FmpClient fmpClient;
    // FinnhubClient 도 mock — config 가 EarningsResultSyncService 를 함께 등록하므로 의존성을 채워야 한다.
    // 본 테스트 클래스는 FinnhubClient 를 직접 사용하지 않지만 컨텍스트 로드용.
    @MockBean private FinnhubClient finnhubClient;

    private Long stockIdA;
    private Long stockIdB;

    @BeforeEach
    void setUp() {
        // 매 테스트마다 데이터 정리. 본 테스트는 트랜잭션 NOT 적용이므로 자동 롤백 없음 → 명시적 wipe.
        stockMetaRepository.deleteAllInBatch();
        stockRepository.deleteAllInBatch();

        // setUp 도 트랜잭션 외 영역이라 save 가 즉시 commit 된다 — 의도된 동작.
        Stock a = stockRepository.save(Stock.builder()
                .ticker("AAA").companyName("Alpha Corp").sector("TECH").build());
        Stock b = stockRepository.save(Stock.builder()
                .ticker("BBB").companyName("Bravo Inc").sector("TECH").build());
        stockIdA = a.getId();
        stockIdB = b.getId();
    }

    // ───────────────────────────────── S1. 정상 ticker 단독 → commit ─────────────────────────────────

    @Test
    @DisplayName("S1: 정상 응답 시 syncTicker 가 새 EntityManager 에서 조회 가능하도록 commit 한다")
    void s1_정상_ticker_commit_성공() {
        given(fmpClient.fetchProfile(eq("AAA"), any()))
                .willReturn(Optional.of(profile("AAA", "175.0", "0.96", "75.60-200.30", "3000000000000")));

        boolean result = service.syncTicker(stockIdA, "AAA", SyncPriority.LOW);

        assertThat(result).isTrue();
        // 별도 트랜잭션으로 조회 — service 의 commit 이 실제 DB 까지 도달했는지 확인.
        StockMeta persisted = readInNewTx(() -> stockMetaRepository.findByStock_Id(stockIdA).orElse(null));
        assertThat(persisted).isNotNull();
        assertThat(persisted.getMarketCapUsd()).isEqualByComparingTo("3000000000000");
        assertThat(persisted.getHigh52w()).isEqualByComparingTo("200.30");
        assertThat(persisted.getLow52w()).isEqualByComparingTo("75.60");
    }

    // ───────────────────── S2. ★ 핵심: ticker A 실패 시 ticker B commit 보존 ─────────────────────

    @Test
    @DisplayName("S2: ticker A PersistenceException 시에도 ticker B 의 commit 은 보존된다 (★ 핵심)")
    void s2_ticker_A_persistenceException_시_ticker_B_commit_보존() {
        // ticker A: marketCap 정수부 19자리 — DECIMAL(20,2) 한도(정수부 18자리) 초과 → DataException
        //          → service 의 ticker A 트랜잭션 rollback + RuntimeException propagate
        given(fmpClient.fetchProfile(eq("AAA"), any()))
                .willReturn(Optional.of(profile(
                        "AAA",
                        "100.0",
                        "1.00",
                        "50.00-150.00",
                        "1234567890123456789" // 19자리 정수부 — overflow
                )));
        // ticker B: 정상 응답
        given(fmpClient.fetchProfile(eq("BBB"), any()))
                .willReturn(Optional.of(profile("BBB", "200.0", "2.00", "100.00-300.00", "5000000000000")));

        // 스케줄러 흉내 — per-ticker try/catch
        List<String> failed = new ArrayList<>();
        for (String ticker : List.of("AAA", "BBB")) {
            Long stockId = ticker.equals("AAA") ? stockIdA : stockIdB;
            try {
                service.syncTicker(stockId, ticker, SyncPriority.LOW);
            } catch (RuntimeException e) {
                failed.add(ticker);
            }
        }

        // ticker A 는 실패해야 한다 (overflow 가 propagate).
        assertThat(failed).containsExactly("AAA");

        // 검증 1 — ticker A 의 StockMeta 는 rollback 되어 영속화되지 않았다.
        StockMeta metaA = readInNewTx(() -> stockMetaRepository.findByStock_Id(stockIdA).orElse(null));
        assertThat(metaA).as("ticker A 는 rollback 되어 영속화되지 않아야 함").isNull();

        // 검증 2 — ★ ticker B 의 StockMeta 는 ticker A 와 무관하게 commit 되어야 한다.
        StockMeta metaB = readInNewTx(() -> stockMetaRepository.findByStock_Id(stockIdB).orElse(null));
        assertThat(metaB).as("ticker B 의 commit 은 ticker A 의 rollback 과 격리되어야 함").isNotNull();
        assertThat(metaB.getMarketCapUsd()).isEqualByComparingTo("5000000000000");
        assertThat(metaB.getHigh52w()).isEqualByComparingTo("300.00");
    }

    // ─────────────────── S3. 외부 client 가 RuntimeException → 격리 + propagate ───────────────────

    @Test
    @DisplayName("S3: 외부 client RuntimeException 도 ticker 단위로 격리되며 propagate 된다")
    void s3_client_RuntimeException_시_다른_ticker_영향_없음() {
        // ticker A: client 자체가 RuntimeException throw — service 가 catch 하지 않고 propagate 해야 한다
        given(fmpClient.fetchProfile(eq("AAA"), any()))
                .willThrow(new RuntimeException("simulated upstream failure"));
        // ticker B: 정상
        given(fmpClient.fetchProfile(eq("BBB"), any()))
                .willReturn(Optional.of(profile("BBB", "100.0", "1.00", "50.00-150.00", "1000")));

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
        assertThat(readInNewTx(() -> stockMetaRepository.findByStock_Id(stockIdA).orElse(null)))
                .as("ticker A 는 영속화 미진입 — 영속화 전 client 단계에서 throw").isNull();
        assertThat(readInNewTx(() -> stockMetaRepository.findByStock_Id(stockIdB).orElse(null)))
                .as("ticker B 의 commit 은 보존").isNotNull();
    }

    // ─────────────────────────── helpers ───────────────────────────

    /**
     * 별도 트랜잭션에서 read 만 수행 — service 가 commit 한 데이터가 실제 DB 까지 반영되었는지
     * (= 다른 트랜잭션에서 보이는지) 검증한다. 같은 EntityManager 캐시에 의존하면 안 된다.
     */
    private <T> T readInNewTx(java.util.function.Supplier<T> action) {
        return transactionTemplate.execute(status -> action.get());
    }

    private static FmpProfile profile(String symbol,
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
}
