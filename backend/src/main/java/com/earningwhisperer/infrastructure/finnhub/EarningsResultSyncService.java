package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubEarningsRow;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

/**
 * 한 ticker 단위 어닝 결과(EPS surprise) 동기화의 영속화 책임을 가진 서비스.
 *
 * <p>{@link com.earningwhisperer.infrastructure.fmp.StockMetaSyncService} 와 동일한 패턴:
 * ticker 단위 {@code @Transactional} 격리 — 한 ticker 의 JPA 예외가 다른 ticker 의 commit 을
 * rollback-only 로 만들지 않도록 빈을 분리한다 (스케줄러 self-invocation 함정 회피).
 *
 * <p>FINNHUB_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Service
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class EarningsResultSyncService {

    /**
     * Finnhub `/stock/earnings` 응답에 명시적 발표 시각이 없을 때의 디폴트.
     * 장중(13:00 UTC ≈ NYSE 09:00 ET) 으로 가정 — 가격반응 계산기가 ±1 영업일 봉 윈도로 보정한다.
     */
    private static final LocalTime DEFAULT_ANNOUNCEMENT_TIME = LocalTime.of(13, 0);

    /**
     * surprisePercent 계산 시 BigDecimal divide 에 적용할 scale.
     * 응답 컬럼 {@code DECIMAL(8,4)} 한도에 맞춰 4자리 + 여유분.
     */
    private static final int SURPRISE_SCALE = 6;

    private final FinnhubClient finnhubClient;
    private final StockRepository stockRepository;
    private final EarningsResultRepository earningsResultRepository;

    /**
     * 한 ticker 의 fetchEarningsHistory + (stock_id, announced_at) upsert.
     *
     * <p>의미적 책임:
     * <ul>
     *     <li>응답 비어있음 → {@code 0} 반환</li>
     *     <li>Stock 미존재 → {@code 0} 반환 (영속화 미진입)</li>
     *     <li>각 row 별 unique constraint 매칭으로 update / insert 분기. 신규 insert 만 카운트.</li>
     * </ul>
     *
     * @param stockId  영속화 대상 Stock 의 PK
     * @param ticker   외부 호출 키
     * @param priority Finnhub rate limiter 우선순위 (사용자 trigger=HIGH, 사전 동기화=LOW)
     * @return 신규 insert 된 row 수 (스케줄러 사이클 요약용)
     */
    @Transactional
    public int syncTicker(Long stockId, String ticker, SyncPriority priority) {
        List<FinnhubEarningsRow> rows = finnhubClient.fetchEarningsHistory(
                ticker, priority.toFinnhub());

        if (rows.isEmpty()) {
            log.warn("[EarningsResultSync] earnings 조회 실패/빈 응답 ticker={}", ticker);
            return 0;
        }

        // 트랜잭션 분리 후에는 외부 트랜잭션이 없으므로 stockId 로 reattach.
        // stockId 가 invalidated 된 경우(삭제 race) ticker 로 fallback.
        Stock attached = stockRepository.findById(stockId)
                .orElseGet(() -> stockRepository.findByTicker(ticker).orElse(null));
        if (attached == null) {
            log.warn("[EarningsResultSync] Stock 미존재 ticker={} stockId={} — skip", ticker, stockId);
            return 0;
        }

        int inserted = 0;
        for (FinnhubEarningsRow row : rows) {
            if (row.period() == null) continue;
            Instant announcedAt = row.period()
                    .atTime(DEFAULT_ANNOUNCEMENT_TIME)
                    .toInstant(ZoneOffset.UTC);
            String fiscalLabel = buildFiscalLabel(row);
            BigDecimal surprisePercent = resolveSurprisePercent(row);

            Optional<EarningsResult> existing = earningsResultRepository
                    .findByStock_IdAndAnnouncedAt(attached.getId(), announcedAt);

            if (existing.isPresent()) {
                existing.get().updateActuals(row.epsEstimate(), row.epsActual(), surprisePercent);
            } else {
                earningsResultRepository.save(EarningsResult.builder()
                        .stock(attached)
                        .announcedAt(announcedAt)
                        .fiscalPeriodLabel(fiscalLabel)
                        .epsEstimate(row.epsEstimate())
                        .epsActual(row.epsActual())
                        .surprisePercent(surprisePercent)
                        .priceReactionPercent(null)
                        .build());
                inserted++;
            }
        }
        return inserted;
    }

    /**
     * surprisePercent 결정.
     *
     * <p>응답 필드가 있으면 그대로. 없으면 {@code (actual - estimate) / abs(estimate) * 100} 로 보강.
     * estimate=0 / 둘 중 하나 null 인 경우는 계산 불가 → null.
     */
    static BigDecimal resolveSurprisePercent(FinnhubEarningsRow row) {
        if (row.surprisePercent() != null) {
            return row.surprisePercent();
        }
        BigDecimal actual = row.epsActual();
        BigDecimal estimate = row.epsEstimate();
        if (actual == null || estimate == null || estimate.signum() == 0) {
            return null;
        }
        return actual.subtract(estimate)
                .divide(estimate.abs(), SURPRISE_SCALE, RoundingMode.HALF_UP)
                .multiply(BigDecimal.valueOf(100));
    }

    /**
     * fiscalPeriodLabel 결정.
     *
     * <p>"Q{n} FY{yy}" 형태. quarter 가 응답에 있으면 그대로, 없으면 period 의 월에서 derive.
     * fiscal year 정보가 응답에 별도로 없어 calendar year 의 2자리 사용.
     * (정확한 fiscal year 매핑은 ai-engine 영역 — 본 phase 는 derived label 만 제공.)
     */
    static String buildFiscalLabel(FinnhubEarningsRow row) {
        String quarter = row.quarterLabel();
        if (quarter == null) {
            quarter = "Q?";
        }
        if (row.period() == null) {
            return quarter + " FY??";
        }
        int yy = row.period().getYear() % 100;
        return String.format("%s FY%02d", quarter, yy);
    }
}
