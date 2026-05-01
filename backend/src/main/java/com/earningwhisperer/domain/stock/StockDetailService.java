package com.earningwhisperer.domain.stock;

import com.earningwhisperer.domain.earnings.EarningsCalendar;
import com.earningwhisperer.domain.earnings.EarningsCalendarRepository;
import com.earningwhisperer.domain.earnings.EarningsResult;
import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.infrastructure.stock.LazyFetchResult;
import com.earningwhisperer.infrastructure.stock.LazyFetchService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * Phase 3: 종목 상세 통합 조회 서비스.
 *
 * <p>흐름:
 * <ol>
 *     <li>ticker 정규식 검증 (실패 시 IllegalArgumentException → 컨트롤러가 400)</li>
 *     <li>{@link LazyFetchService} Bean 이 있으면 {@code ensureExists} 로 미존재 데이터 동기 fetch.
 *         {@link LazyFetchResult#allFailed()} && Stock 도 없음 → empty Optional (503)</li>
 *     <li>Stock 없으면 empty Optional (503)</li>
 *     <li>StockMeta / DailyBar(30개) / EarningsResult(4건) / 가장 가까운 미래 EarningsCalendar 통합</li>
 *     <li>partial 플래그 계산 후 {@link StockDetailResponse} 반환</li>
 * </ol>
 *
 * <p>LazyFetchService 는 {@code Optional<LazyFetchService>} 로 주입 — FMP/Finnhub 키 미설정 시
 * Bean 미등록되어도 Service 자체는 정상 동작 (DB 데이터만 반환).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class StockDetailService {

    private static final Pattern TICKER_PATTERN = Pattern.compile("^[A-Z0-9.-]{1,10}$");

    private final StockRepository stockRepository;
    private final StockMetaRepository stockMetaRepository;
    private final DailyBarRepository dailyBarRepository;
    private final EarningsResultRepository earningsResultRepository;
    private final EarningsCalendarRepository earningsCalendarRepository;

    /**
     * Optional 주입 — LazyFetchService Bean 이 등록되지 않은 환경(API 키 미설정)에서도 정상 기동.
     */
    private final Optional<LazyFetchService> lazyFetchService;

    /**
     * ticker 로 종목 상세 조회.
     *
     * <p>본 메서드는 클래스/메서드 레벨 {@code @Transactional} 을 가지지 않는다.
     * <ul>
     *     <li>{@link LazyFetchService#ensureExists}: 외부 HTTP + Stock save + 자체 ticker 단위
     *         {@code @Transactional} 을 가진 sync service 들. 외부 부모 readOnly 트랜잭션에 묶이면
     *         (a) save 시 readOnly 위반, (b) HTTP 응답 지연 동안 DB 커넥션 점유로 풀 고갈 위험.</li>
     *     <li>DB 조회: 각 {@code JpaRepository} 의 default {@code @Transactional} 이 자체 적용된다.
     *         한 응답에서 4~5개 트랜잭션이 발생하지만 데이터 일관성 영향 미미하고 readOnly 트랜잭션
     *         의 외부 호출 안티패턴을 회피하는 트레이드오프.</li>
     * </ul>
     *
     * @return Stock 자체가 없는 외부 의존성 장애 케이스에서는 {@link Optional#empty()} 반환.
     *         호출자(컨트롤러)가 503 으로 응답한다.
     * @throws IllegalArgumentException ticker 가 정규식 미통과
     */
    public Optional<StockDetailResponse> getDetail(String ticker) {
        if (ticker == null || !TICKER_PATTERN.matcher(ticker).matches()) {
            throw new IllegalArgumentException("invalid ticker: " + ticker);
        }

        // ─── 1. Lazy fetch (Bean 존재 시) ─────────────────────────────
        if (lazyFetchService.isPresent()) {
            LazyFetchResult result;
            try {
                result = lazyFetchService.get().ensureExists(ticker);
            } catch (IllegalArgumentException iae) {
                // 정규식은 위에서 통과했으므로 여기 도달하면 service 측 미스매치 — 그대로 위임
                throw iae;
            } catch (RuntimeException e) {
                log.warn("[StockDetail] LazyFetch 전체 throw ticker={} — DB fallback 시도", ticker, e);
                result = null;
            }

            if (result != null && result.allFailed()
                    && stockRepository.findByTicker(ticker).isEmpty()) {
                // 모든 외부 시도 실패 + Stock 도 없음 → 503
                log.warn("[StockDetail] 모든 외부 fetch 시도 실패 + Stock 미존재 ticker={}", ticker);
                return Optional.empty();
            }
        }

        // ─── 2. Stock 조회 ─────────────────────────────────────────────
        Optional<Stock> stockOpt = stockRepository.findByTicker(ticker);
        if (stockOpt.isEmpty()) {
            return Optional.empty();
        }
        Stock stock = stockOpt.get();
        Long stockId = stock.getId();

        // ─── 3. 부속 데이터 조회 ───────────────────────────────────────
        StockDetailResponse.BasicInfo basic = stockMetaRepository.findByStock_Id(stockId)
                .map(StockDetailService::toBasicInfo)
                .orElse(null);

        List<StockDetailResponse.DailyBarPoint> chart30d =
                toChartAscending(dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(stockId));

        BigDecimal currentPrice = chart30d.isEmpty()
                ? null
                : chart30d.get(chart30d.size() - 1).close();

        List<StockDetailResponse.EarningsHistoryItem> earningsHistory =
                earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockId).stream()
                        .map(StockDetailService::toEarningsHistoryItem)
                        .toList();

        StockDetailResponse.NextEarning nextEarning = earningsCalendarRepository
                .findFirstByStock_IdAndScheduledAtAfterOrderByScheduledAtAsc(stockId, Instant.now())
                .map(StockDetailService::toNextEarning)
                .orElse(null);

        // ─── 4. partial 판정 ──────────────────────────────────────────
        // placeholder Stock(active=false) / 메타 누락 / 차트 누락 / (어닝 결과 + 다음 어닝) 모두 누락
        // 중 하나라도 만족하면 partial.
        boolean partial = !stock.isActive()
                || basic == null
                || chart30d.isEmpty()
                || (earningsHistory.isEmpty() && nextEarning == null);

        return Optional.of(new StockDetailResponse(
                stock.getTicker(),
                stock.getCompanyName(),
                stock.getSector(),
                stock.isActive(),
                basic,
                chart30d,
                currentPrice,
                earningsHistory,
                nextEarning,
                partial,
                null
        ));
    }

    private static StockDetailResponse.BasicInfo toBasicInfo(StockMeta meta) {
        return new StockDetailResponse.BasicInfo(
                meta.getMarketCapUsd(),
                meta.getHigh52w(),
                meta.getLow52w(),
                meta.getDividendYield()
        );
    }

    /**
     * Repository 결과는 {@code BarDate DESC} (최신 → 과거) 순. 클라이언트 차트는 시간순(과거 → 최신)이
     * 자연스러우므로 reverse 한다. 마지막 element 가 currentPrice 추출 대상이 되도록 보장.
     */
    private static List<StockDetailResponse.DailyBarPoint> toChartAscending(List<DailyBar> descBars) {
        if (descBars.isEmpty()) {
            return Collections.emptyList();
        }
        List<DailyBar> ascending = new ArrayList<>(descBars);
        Collections.reverse(ascending);
        List<StockDetailResponse.DailyBarPoint> points = new ArrayList<>(ascending.size());
        for (DailyBar bar : ascending) {
            points.add(new StockDetailResponse.DailyBarPoint(
                    bar.getBarDate(),
                    bar.getClosePrice(),
                    bar.getVolume()
            ));
        }
        return points;
    }

    private static StockDetailResponse.EarningsHistoryItem toEarningsHistoryItem(EarningsResult er) {
        return new StockDetailResponse.EarningsHistoryItem(
                er.getFiscalPeriodLabel(),
                er.getAnnouncedAt().getEpochSecond(),
                er.getEpsEstimate(),
                er.getEpsActual(),
                er.getSurprisePercent(),
                er.getPriceReactionPercent()
        );
    }

    private static StockDetailResponse.NextEarning toNextEarning(EarningsCalendar ec) {
        return new StockDetailResponse.NextEarning(
                ec.getScheduledAt().getEpochSecond(),
                ec.getEpsEstimate(),
                ec.getRevenueEstimate(),
                ec.isConfirmed()
        );
    }
}
