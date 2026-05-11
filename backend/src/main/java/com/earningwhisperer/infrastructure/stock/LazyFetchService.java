package com.earningwhisperer.infrastructure.stock;

import com.earningwhisperer.domain.earnings.EarningsResultRepository;
import com.earningwhisperer.domain.stock.DailyBarRepository;
import com.earningwhisperer.domain.stock.Stock;
import com.earningwhisperer.domain.stock.StockMetaRepository;
import com.earningwhisperer.domain.stock.StockRepository;
import com.earningwhisperer.global.common.SyncPriority;
import com.earningwhisperer.infrastructure.finnhub.EarningsResultSyncService;
import com.earningwhisperer.infrastructure.fmp.DailyBarSyncService;
import com.earningwhisperer.infrastructure.fmp.FmpClient;
import com.earningwhisperer.infrastructure.fmp.StockMetaSyncService;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Service;

import java.util.Optional;
import java.util.regex.Pattern;

/**
 * drawer 첫 열림 시 사전 동기화 대상이 아닌 ticker 의 동기 fetch 진입점.
 *
 * <p>대상:
 * <ul>
 *     <li>KIS 보유종목 중 비-S&P 500 ticker (옵션 B 정책 — Stock 엔티티가 없으면 placeholder 등록)</li>
 *     <li>사전 동기화 사이클(StockMetaSync / DailyBarSync / EarningsResultSync)에서 누락된 신규 ticker</li>
 * </ul>
 *
 * <p><b>정책 단순화</b>: 본 서비스는 "DB 에 데이터가 한 row 도 없는 ticker" 만 처리한다. stale 갱신은
 * 사전 동기화 스케줄러에 일임 — lazy fetch 는 신규 ticker 의 cold-start 비용만 부담한다.
 *
 * <p>모든 외부 호출은 {@link SyncPriority#HIGH} 로 진행되어 RateLimiter 큐에서 사전 동기화(LOW) 보다
 * 먼저 drain 된다. 한 단계가 throw 해도 다른 단계는 계속 진행되며 {@link LazyFetchResult} 의 해당
 * 단계 플래그만 false 로 남는다 — 호출자가 partial 결과로 판단.
 *
 * <p>FMP_API_KEY 와 FINNHUB_API_KEY 가 모두 설정된 경우에만 Bean 등록. 본 서비스는 두 vendor 모두에
 * 의존한다.
 */
@Service
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank() && !'${finnhub.api-key:}'.isBlank()")
@RequiredArgsConstructor
@Slf4j
public class LazyFetchService {

    /**
     * 허용 ticker 패턴 — 영문 대문자/숫자/마침표/하이픈, 1~10자.
     *
     * <p>NYSE/NASDAQ 의 일반 ticker 외에 BRK.B, BF-B 등 마침표/하이픈 포함 ticker 까지 허용.
     * 호출자(Phase 3 REST) 가 이미 검증한 ticker 라도 service 진입 시 한 번 더 검증하여
     * 외부 API 에 의도치 않은 입력이 흘러 들어가는 것을 방지한다.
     */
    private static final Pattern TICKER_PATTERN = Pattern.compile("^[A-Z0-9.-]{1,10}$");

    private final StockRepository stockRepository;
    private final StockMetaRepository stockMetaRepository;
    private final DailyBarRepository dailyBarRepository;
    private final EarningsResultRepository earningsResultRepository;

    private final FmpClient fmpClient;
    private final StockMetaSyncService stockMetaSyncService;
    private final DailyBarSyncService dailyBarSyncService;
    private final EarningsResultSyncService earningsResultSyncService;

    /** Phase 2-C 가격반응 ±10일 윈도 + 여유분 — 사전 동기화 스케줄러 ({@code DailyBarSyncScheduler}) 와 동일. */
    private static final int LAZY_HISTORICAL_DAYS = 30;

    /**
     * ticker 가 DB 에 없거나 메타/일봉/어닝 결과 중 하나라도 한 row 도 없으면 동기 fetch.
     *
     * <p>각 단계는 독립적으로 try/catch 되며 한 단계 실패가 다른 단계로 전파되지 않는다.
     * 호출자는 {@link LazyFetchResult} 의 boolean 플래그로 어떤 데이터가 채워졌는지 판단.
     *
     * @param ticker 정규식 {@code [A-Z0-9.-]{1,10}} 통과해야 함
     * @return 단계별 적재 결과
     * @throws IllegalArgumentException ticker 가 정규식 미통과
     */
    public LazyFetchResult ensureExists(String ticker) {
        if (ticker == null || !TICKER_PATTERN.matcher(ticker).matches()) {
            throw new IllegalArgumentException("invalid ticker: " + ticker);
        }

        // ─── 1단계: Stock 확보 ─────────────────────────────────────────
        // TODO(후속): 동시 ensureExists 호출이 같은 ticker 에 대해 중복 save 시도 시 unique 제약 위반.
        //  현재 단일 사용자 가정이라 race 빈도 낮음. 후속 개선 (DataIntegrityViolation 시 findByTicker
        //  retry, 또는 분산 lock) 은 본 PR 범위 외.
        Optional<Stock> existingStockOpt = stockRepository.findByTicker(ticker);
        boolean stockCreated = false;
        boolean profileMissing = false;
        boolean stockAttempted = false;
        Stock stock;

        if (existingStockOpt.isPresent()) {
            stock = existingStockOpt.get();
        } else {
            stockAttempted = true;
            FetchedStock fetched = createStock(ticker);
            stock = fetched.stock();
            stockCreated = (stock != null);
            profileMissing = fetched.profileMissing();

            if (stock == null) {
                // Stock 등록 자체가 throw 한 케이스 — 후속 단계 진행 불가
                log.warn("[LazyFetch] Stock 등록 실패 ticker={} — 후속 단계 skip", ticker);
                return new LazyFetchResult(
                        ticker, false, false, false, false, profileMissing,
                        stockAttempted, false, false, false);
            }
        }

        Long stockId = stock.getId();

        // ─── 2단계: StockMeta ─────────────────────────────────────────
        boolean metaFetched = false;
        boolean metaAttempted = false;
        if (stockMetaRepository.findByStock_Id(stockId).isEmpty()) {
            metaAttempted = true;
            try {
                metaFetched = stockMetaSyncService.syncTicker(stockId, ticker, SyncPriority.HIGH);
            } catch (RuntimeException e) {
                log.warn("[LazyFetch] StockMeta 동기 fetch 실패 ticker={}", ticker, e);
            }
        }

        // ─── 3단계: DailyBar ─────────────────────────────────────────
        boolean dailyBarsFetched = false;
        boolean dailyBarsAttempted = false;
        if (!dailyBarRepository.findTop30ByStock_IdOrderByBarDateDesc(stockId).isEmpty()) {
            // 이미 한 row 라도 있으면 lazy fetch skip — stale 갱신은 사전 동기화 스케줄러 책임.
            dailyBarsFetched = false;
        } else {
            dailyBarsAttempted = true;
            try {
                int processed = dailyBarSyncService.syncTicker(
                        stockId, ticker, LAZY_HISTORICAL_DAYS, SyncPriority.HIGH);
                dailyBarsFetched = processed > 0;
            } catch (RuntimeException e) {
                log.warn("[LazyFetch] DailyBar 동기 fetch 실패 ticker={}", ticker, e);
            }
        }

        // ─── 4단계: EarningsResult ───────────────────────────────────
        boolean earningsFetched = false;
        boolean earningsAttempted = false;
        if (earningsResultRepository.findTop4ByStock_IdOrderByAnnouncedAtDesc(stockId).isEmpty()) {
            earningsAttempted = true;
            try {
                int inserted = earningsResultSyncService.syncTicker(stockId, ticker, SyncPriority.HIGH);
                earningsFetched = inserted > 0;
            } catch (RuntimeException e) {
                log.warn("[LazyFetch] EarningsResult 동기 fetch 실패 ticker={}", ticker, e);
            }
        }

        return new LazyFetchResult(
                ticker, stockCreated, metaFetched, dailyBarsFetched, earningsFetched, profileMissing,
                stockAttempted, metaAttempted, dailyBarsAttempted, earningsAttempted);
    }

    /**
     * Stock 미존재 시 신규 등록.
     *
     * <p>FMP profile 호출 결과:
     * <ul>
     *     <li>응답 있음 → companyName/sector 채움, active=true (기본값)</li>
     *     <li>응답 없음 → placeholder (companyName=ticker, sector=null, active=false)
     *         사용자가 KIS 보유 ticker 인 경우 이후 사전 동기화나 또 다른 lazy fetch 사이클에서
     *         정상 정보로 갱신될 수 있도록 row 자체는 남겨둔다.</li>
     * </ul>
     *
     * <p>save 자체가 throw 하면 (예: unique 제약 race) Stock 등록 실패로 처리. 호출자가 후속
     * 단계 skip 결정. 본 메서드는 {@code @Transactional} 을 가지지 않는다 — Spring 의 default
     * propagation 으로 save 는 자동 커밋된다. 후속 sync service 들이 자체 트랜잭션을 가지므로
     * Stock 신규 등록과 메타/일봉/어닝 적재가 같은 트랜잭션에 묶이지 않아 한 단계 실패가 다른
     * 단계의 영속화를 rollback 시키지 않는다.
     */
    private FetchedStock createStock(String ticker) {
        Optional<FmpProfile> profileOpt;
        try {
            profileOpt = fmpClient.fetchProfile(ticker, SyncPriority.HIGH.toFmp());
        } catch (RuntimeException e) {
            // FmpClient 는 정상 경로에서 throw 하지 않으나 RateLimiter 등 인프라 예외 방어.
            log.warn("[LazyFetch] FMP profile 조회 예외 ticker={}", ticker, e);
            profileOpt = Optional.empty();
        }

        boolean profileMissing = profileOpt.isEmpty();
        Stock toSave;
        if (profileMissing) {
            // placeholder — companyName 자리에 ticker 그대로, sector null, deactivate.
            toSave = Stock.builder()
                    .ticker(ticker)
                    .companyName(ticker)
                    .sector(null)
                    .build();
            toSave.deactivate();
            log.info("[LazyFetch] Stock placeholder 등록 (profile 빈 응답) ticker={}", ticker);
        } else {
            FmpProfile profile = profileOpt.get();
            String companyName = (profile.companyName() == null || profile.companyName().isBlank())
                    ? ticker
                    : profile.companyName();
            toSave = Stock.builder()
                    .ticker(ticker)
                    .companyName(companyName)
                    .sector(profile.sector())
                    .build();
            log.info("[LazyFetch] Stock 신규 등록 ticker={} companyName={}", ticker, companyName);
        }

        try {
            Stock saved = stockRepository.save(toSave);
            return new FetchedStock(saved, profileMissing);
        } catch (RuntimeException e) {
            // unique 제약 race 등 — Stock null 반환으로 후속 단계 skip.
            log.warn("[LazyFetch] Stock save 실패 ticker={}", ticker, e);
            return new FetchedStock(null, profileMissing);
        }
    }

    /** Stock 신규 등록 결과를 createStock 호출자에게 단일 객체로 반환. */
    private record FetchedStock(Stock stock, boolean profileMissing) {
    }
}
