package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.DailyBar;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

/**
 * 어닝 결과 row 단위 가격반응(price reaction %) 산출 서비스.
 *
 * <p>{@link EarningsResult#priceReactionPercent} 가 NULL 인 row 를 받아
 * 발표일 ±N 영업일 일봉을 조회 → {@code (after_close - before_close) / before_close * 100} 로 계산.
 *
 * <p>Phase 2-B 패턴 일관성을 위해 row 단위 {@code @Transactional} 격리:
 * 한 row 의 JPA 예외가 다른 row 의 commit 을 rollback-only 로 만들지 않는다.
 *
 * <p>{@link EarningsResultSyncService} 와 동일 패키지에 둔 사유:
 * Finnhub 어닝 결과의 후속 처리(가격반응 백필) — 도메인 응집도 측면에서 같은 패키지 유지.
 *
 * <p>본 서비스는 외부 API 미호출 — DailyBar 가 미리 적재되어 있어야 한다
 * ({@link com.earningwhisperer.infrastructure.fmp.DailyBarSyncScheduler} 가 22:30 UTC 에 적재).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class PriceReactionCalculatorService {

    /**
     * 발표일 기준 ±N 일 윈도. 주말/공휴일(미국 시장 기준 연 ~10일) 흡수 위해 7일.
     * 더 좁히면 long weekend / 단기 휴장에 before/after 일봉을 못 찾는 경우 발생.
     */
    static final int WINDOW_DAYS = 7;

    /**
     * DECIMAL(8,4) 한도(±9999.9999) 가드.
     * 한도를 살짝 넘는 정상 값(예: 9999.5)도 컬럼 저장이 안 되므로,
     * 컬럼 최대치 9999.9999 까지만 허용하고 그 이상은 데이터 오류로 판단해 null 유지.
     */
    static final BigDecimal MAX_REACTION_ABS = new BigDecimal("9999.9999");

    private static final int DIVIDE_SCALE = 6;
    private static final int RESULT_SCALE = 4;

    private final EarningsResultRepository earningsResultRepository;
    private final DailyBarRepository dailyBarRepository;

    /**
     * 한 EarningsResult row 의 가격반응 산출 + update.
     *
     * @param earningsResultId 대상 row PK
     * @return {@link PriceReactionResult#COMPUTED} 정상 / {@link PriceReactionResult#DATA_MISSING}
     *         일봉 부족(재시도 가치 있음) / {@link PriceReactionResult#DATA_ERROR} 데이터 오류(영구 skip)
     */
    @Transactional
    public PriceReactionResult computeAndUpdate(Long earningsResultId) {
        Optional<EarningsResult> opt = earningsResultRepository.findById(earningsResultId);
        if (opt.isEmpty()) {
            log.warn("[PriceReaction] EarningsResult 미존재 id={}", earningsResultId);
            return PriceReactionResult.DATA_ERROR;
        }
        EarningsResult er = opt.get();
        return computeAndUpdate(er);
    }

    /**
     * 영속화된 EarningsResult 객체를 받아 가격반응 산출 + update.
     * 호출자가 이미 entity 를 보유한 경우(스케줄러) 의 fast-path.
     */
    PriceReactionResult computeAndUpdate(EarningsResult er) {
        if (er.getStock() == null || er.getStock().getId() == null) {
            log.warn("[PriceReaction] Stock 미존재 — skip earningsResultId={}", er.getId());
            return PriceReactionResult.DATA_ERROR;
        }
        String ticker = er.getStock().getTicker();

        LocalDate eventDate = er.getAnnouncedAt().atZone(ZoneOffset.UTC).toLocalDate();
        List<DailyBar> bars = dailyBarRepository.findByStock_IdAndBarDateBetween(
                er.getStock().getId(),
                eventDate.minusDays(WINDOW_DAYS),
                eventDate.plusDays(WINDOW_DAYS));

        if (bars.size() < 2) {
            log.warn("[PriceReaction] {} 윈도 내 일봉 부족 (size={}) — skip eventDate={}",
                    ticker, bars.size(), eventDate);
            return PriceReactionResult.DATA_MISSING;
        }

        // 발표일 직전 / 직후 가장 가까운 거래일 봉 추출.
        // 동일 일자 봉이 윈도에 있어도 before / after 로 사용하지 않는다 (장중 발표 가정).
        DailyBar before = bars.stream()
                .filter(b -> b.getBarDate().isBefore(eventDate))
                .max(Comparator.comparing(DailyBar::getBarDate))
                .orElse(null);
        DailyBar after = bars.stream()
                .filter(b -> b.getBarDate().isAfter(eventDate))
                .min(Comparator.comparing(DailyBar::getBarDate))
                .orElse(null);

        if (before == null || after == null) {
            log.warn("[PriceReaction] {} before/after 일봉 부족 — skip eventDate={} before={} after={}",
                    ticker, eventDate,
                    before == null ? null : before.getBarDate(),
                    after == null ? null : after.getBarDate());
            return PriceReactionResult.DATA_MISSING;
        }
        if (before.getClosePrice() == null || before.getClosePrice().signum() <= 0) {
            log.warn("[PriceReaction] {} before close 0 가드 — skip eventDate={} before={}",
                    ticker, eventDate, before.getClosePrice());
            return PriceReactionResult.DATA_ERROR;
        }
        if (after.getClosePrice() == null) {
            log.warn("[PriceReaction] {} after close null — skip eventDate={}", ticker, eventDate);
            return PriceReactionResult.DATA_MISSING;
        }

        BigDecimal pct = after.getClosePrice()
                .subtract(before.getClosePrice())
                .divide(before.getClosePrice(), DIVIDE_SCALE, RoundingMode.HALF_UP)
                .multiply(BigDecimal.valueOf(100))
                .setScale(RESULT_SCALE, RoundingMode.HALF_UP);

        if (pct.abs().compareTo(MAX_REACTION_ABS) > 0) {
            log.warn("[PriceReaction] {} 가격반응 한도 초과 — null 처리: pct={} eventDate={}",
                    ticker, pct, eventDate);
            return PriceReactionResult.DATA_ERROR;
        }

        er.updatePriceReaction(pct);
        return PriceReactionResult.COMPUTED;
    }
}
