package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;

/**
 * 어닝 결과 가격반응(price reaction %) 백필 스케줄러.
 *
 * <p>매일 UTC 23:00 — {@code DailyBarSyncScheduler}(22:30) 이후 30분 버퍼.
 * 가격반응은 ±1 영업일 일봉에 의존하므로 일봉 적재가 끝난 직후에 실행.
 *
 * <p>본 스케줄러는 {@code @Transactional} 을 가지지 않는다. row 단위 트랜잭션은
 * {@link PriceReactionCalculatorService#computeAndUpdate(Long)} 가 관리한다.
 *
 * <p>외부 API 미호출 — Bean 등록에 API key 조건 불필요.
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class PriceReactionCalculatorScheduler {

    /** 사이클 실패율이 임계 이상일 때 ERROR 로그로 승격 — 운영자 알람 트리거. */
    private static final double FAILURE_RATE_ERROR_THRESHOLD = 0.3;

    /**
     * 백필 후보 윈도 — 30일 이전 row 는 가격반응 계산 가치 적음 + 인덱스 효율.
     * 어닝 발표 후 30일이 지나도 priceReactionPercent 가 NULL 이면 시장 휴장 등의 이유로
     * 데이터가 영영 채워지지 않을 가능성이 크다 (반복 try 로 비용만 증가).
     */
    private static final int LOOKBACK_DAYS = 30;

    private final EarningsResultRepository earningsResultRepository;
    private final PriceReactionCalculatorService priceReactionCalculatorService;

    @Scheduled(cron = "0 0 23 * * *", zone = "UTC")
    public void calculatePriceReactions() {
        Instant threshold = Instant.now().minus(LOOKBACK_DAYS, ChronoUnit.DAYS);
        List<EarningsResult> candidates = earningsResultRepository
                .findByPriceReactionPercentIsNullAndAnnouncedAtAfter(threshold);

        if (candidates.isEmpty()) {
            log.info("[PriceReaction] 백필 대상 없음 — skip threshold={}", threshold);
            return;
        }

        int total = candidates.size();
        int success = 0;
        int dataMissing = 0;  // 일봉 부족 — 재시도 가치 있음 (다음 사이클이 채울 수 있음)
        int dataError = 0;    // 데이터 오류 — 재시도해도 동일 결과 (운영자 조사 가치)
        int failed = 0;       // RuntimeException — 비정상 종료

        for (EarningsResult er : candidates) {
            if (er == null || er.getId() == null) {
                failed++;
                continue;
            }
            try {
                PriceReactionResult result = priceReactionCalculatorService.computeAndUpdate(er.getId());
                switch (result) {
                    case COMPUTED -> success++;
                    case DATA_MISSING -> dataMissing++;
                    case DATA_ERROR -> dataError++;
                }
            } catch (RuntimeException e) {
                failed++;
                log.warn("[PriceReaction] earningsResultId={} 계산 실패", er.getId(), e);
            }
        }

        logCycleResult(total, success, dataMissing, dataError, failed);
    }

    private void logCycleResult(int total, int success, int dataMissing, int dataError, int failed) {
        // ERROR 승격 기준은 비정상 종료(failed) + 데이터 오류(dataError) 합산 비율.
        // dataMissing 은 다음 사이클이 채울 수 있는 정상 흐름이라 ERROR 트리거에서 제외.
        int errorish = failed + dataError;
        double errorRate = total == 0 ? 0.0 : (double) errorish / total;
        if (errorRate >= FAILURE_RATE_ERROR_THRESHOLD) {
            log.error("[PriceReaction] 오류율 {}% (total={} success={} dataMissing={} dataError={} failed={}) — DB/일봉/source 점검 필요",
                    (int) (errorRate * 100), total, success, dataMissing, dataError, failed);
        } else {
            log.info("[PriceReaction] 가격반응 백필 완료 — total={} success={} dataMissing={} dataError={} failed={}",
                    total, success, dataMissing, dataError, failed);
        }
    }
}
