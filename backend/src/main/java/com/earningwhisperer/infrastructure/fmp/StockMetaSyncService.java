package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockMeta;
import com.earningwhisperer.domain.stock.StockMetaRepository;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Optional;

/**
 * 한 ticker 단위 종목 메타 동기화의 영속화 책임을 가진 서비스.
 *
 * <p>스케줄러에서 분리된 사유:
 * 한 ticker 의 JPA 작업이 PersistenceException 류를 던지면 Spring 이 트랜잭션을
 * rollback-only 로 마킹한다. 스케줄러 단일 메서드에 {@code @Transactional} 을 걸고 per-ticker
 * try/catch 로 진행하면 catch 후 다음 ticker 들이 정상 처리되는 듯 보이지만 commit 시점에
 * {@code UnexpectedRollbackException} 이 터지면서 모든 success 건도 함께 rollback 된다 —
 * silent data loss.
 *
 * <p>해결: ticker 단위 메서드를 별도 빈으로 분리하고 자체 {@code @Transactional} 을 적용.
 * 한 ticker 의 실패는 자기 자신만 rollback 시키고 propagate 되어 스케줄러가 catch 한다.
 *
 * <p>FMP_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Service
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class StockMetaSyncService {

    /**
     * dividendYield 컬럼은 {@code DECIMAL(8,6)} — 정수부 2자리 한도(0.000000 ~ 99.999999).
     * yield ≥ 100 (= price < lastDiv) 시 {@code DataException} 으로 사이클 abort 가능하므로
     * 임계 초과 시 null 처리하고 WARN 로그.
     */
    private static final BigDecimal MAX_DIVIDEND_YIELD = BigDecimal.valueOf(100);

    private final FmpClient fmpClient;
    private final StockRepository stockRepository;
    private final StockMetaRepository stockMetaRepository;

    /**
     * 한 ticker 의 fetchProfile + DB upsert.
     *
     * <p>의미적 책임:
     * <ul>
     *     <li>profile 빈 응답 → {@code false} 반환 (실패 카운트, 영속화 미진입)</li>
     *     <li>정상 적재 완료 → {@code true} 반환</li>
     *     <li>JPA / runtime 예외 → 자체 트랜잭션 rollback 후 propagate (스케줄러가 catch)</li>
     * </ul>
     *
     * @param stockId  영속화 대상 Stock 의 PK
     * @param ticker   로깅 / fallback 용 ticker (외부 호출 키)
     * @param priority FMP rate limiter 우선순위 (사용자 trigger=HIGH, 사전 동기화=LOW)
     * @return 영속화 성공 여부
     */
    @Transactional
    public boolean syncTicker(Long stockId, String ticker, SyncPriority priority) {
        Optional<FmpProfile> profileOpt = fmpClient.fetchProfile(ticker, priority.toFmp());

        if (profileOpt.isEmpty()) {
            log.warn("[StockMetaSync] profile 조회 실패 ticker={}", ticker);
            return false;
        }

        FmpProfile profile = profileOpt.get();
        BigDecimal marketCap = profile.mktCap();
        BigDecimal high52w = profile.high52w().orElse(null);
        BigDecimal low52w = profile.low52w().orElse(null);
        BigDecimal dividendYield = computeDividendYield(profile.lastDiv(), profile.price(), ticker);

        // 트랜잭션 분리 후에는 외부 트랜잭션이 없으므로 stockId 로 reattach.
        // 보유한 stockId 가 invalidated 된 경우(삭제 race) ticker 로 fallback.
        Stock attached = stockRepository.findById(stockId)
                .orElseGet(() -> stockRepository.findByTicker(ticker).orElse(null));
        if (attached == null) {
            log.warn("[StockMetaSync] Stock 미존재 ticker={} stockId={} — skip", ticker, stockId);
            return false;
        }

        Optional<StockMeta> existing = stockMetaRepository.findByStock_Id(attached.getId());
        if (existing.isPresent()) {
            existing.get().updateMeta(marketCap, high52w, low52w, dividendYield);
        } else {
            stockMetaRepository.save(StockMeta.builder()
                    .stock(attached)
                    .marketCapUsd(marketCap)
                    .high52w(high52w)
                    .low52w(low52w)
                    .dividendYield(dividendYield)
                    .build());
        }
        return true;
    }

    /**
     * 배당수익률 계산. FMP {@code lastDiv} 는 연 배당금($, TTM) — 가격 대비 비율로 환산.
     *
     * <p>price 가 null 또는 0 이면 yield 도 null (분모 invalid).
     * yield ≥ 100 (= {@code DECIMAL(8,6)} 한도 초과) 이면 null + WARN — DB 적재 시 사이클 abort 방지.
     * 결과는 6자리 소수 (예: 0.004900 ≈ 0.49%).
     */
    static BigDecimal computeDividendYield(BigDecimal lastDiv, BigDecimal price, String ticker) {
        if (lastDiv == null || price == null) return null;
        if (price.signum() <= 0) return null;
        BigDecimal yield = lastDiv.divide(price, 6, RoundingMode.HALF_UP);
        if (yield.compareTo(MAX_DIVIDEND_YIELD) >= 0) {
            log.warn("[StockMetaSync] dividendYield 한도 초과 — null 처리: ticker={} lastDiv={} price={} yield={}",
                    ticker, lastDiv, price, yield);
            return null;
        }
        return yield;
    }
}
