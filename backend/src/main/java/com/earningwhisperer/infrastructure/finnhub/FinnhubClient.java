package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubCalendarResponse;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubCalendarRow;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubEarningsRow;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.time.LocalDate;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubQuote;

import java.util.Collections;
import java.util.List;
import java.util.Optional;

/**
 * Finnhub 외부 API 호출 클라이언트.
 *
 * <p>모든 호출은 {@link FinnhubRateLimiter#acquire(FinnhubRateLimiter.Priority)} 를 통해 게이팅된다.
 * 호출 실패(네트워크/4xx/5xx) 또는 rate limiter 비정상 종료 시 빈 결과를 반환하고 WARN 로그만
 * 남긴다 — 호출자는 graceful fallback(예: 마지막 캐시값 유지) 을 수행할 수 있다.
 *
 * <p>API 키는 Finnhub 표준 헤더 {@code X-Finnhub-Token} 로 전달한다. (기존 스케줄러는 query
 * 파라미터 방식을 사용했으나 Finnhub 권장 방식으로 정리.)
 *
 * <p>FINNHUB_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Component
@ConditionalOnExpression("!'${finnhub.api-key:}'.isBlank()")
@Slf4j
public class FinnhubClient {

    private static final String AUTH_HEADER = "X-Finnhub-Token";

    private final RestClient restClient;
    private final FinnhubProperties properties;
    private final FinnhubRateLimiter rateLimiter;

    public FinnhubClient(@Qualifier("finnhubRestClient") RestClient restClient,
                         FinnhubProperties properties,
                         FinnhubRateLimiter rateLimiter) {
        this.restClient = restClient;
        this.properties = properties;
        this.rateLimiter = rateLimiter;
    }

    /**
     * `/calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD` 호출. 어닝 일정 배열 반환.
     *
     * @return 응답이 비거나 호출이 실패하면 빈 List
     */
    public List<FinnhubCalendarRow> fetchCalendar(LocalDate from,
                                                  LocalDate to,
                                                  FinnhubRateLimiter.Priority priority) {
        try {
            rateLimiter.acquire(priority);
        } catch (FinnhubRateLimitExceededException e) {
            log.warn("[FinnhubClient] calendar rate limited from={} to={} priority={} reason={}",
                    from, to, priority, e.getMessage());
            return Collections.emptyList();
        }

        try {
            FinnhubCalendarResponse body = restClient.get()
                    .uri(b -> b.path("/calendar/earnings")
                            .queryParam("from", from.toString())
                            .queryParam("to", to.toString())
                            .build())
                    .header(AUTH_HEADER, properties.apiKey())
                    .retrieve()
                    .body(FinnhubCalendarResponse.class);

            if (body == null || body.earningsCalendar() == null || body.earningsCalendar().isEmpty()) {
                log.warn("[FinnhubClient] calendar empty response from={} to={}", from, to);
                return Collections.emptyList();
            }
            return List.copyOf(body.earningsCalendar());
        } catch (HttpClientErrorException.Unauthorized | HttpClientErrorException.Forbidden e) {
            log.error("[FinnhubClient] calendar 인증 실패 — API 키 확인 필요 from={} to={} status={}",
                    from, to, e.getStatusCode());
            return Collections.emptyList();
        } catch (HttpClientErrorException.TooManyRequests e) {
            log.warn("[FinnhubClient] calendar rate limit (429) — 후속 호출 일시 자제 권장 from={} to={}",
                    from, to);
            return Collections.emptyList();
        } catch (RestClientException e) {
            log.warn("[FinnhubClient] calendar 호출 실패 from={} to={} reason={}",
                    from, to, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * `/quote?symbol={symbol}` 호출. 단일 종목의 현재가/등락률.
     *
     * <p>지수 스트립용이다. 원지수(SPX 등)는 유료라 무료 등급에서는 ETF 로만 받을 수 있다.
     *
     * @return 호출 실패나 가격 없음이면 empty
     */
    public Optional<FinnhubQuote> fetchQuote(String symbol, FinnhubRateLimiter.Priority priority) {
        try {
            rateLimiter.acquire(priority);
        } catch (FinnhubRateLimitExceededException e) {
            log.warn("[FinnhubClient] quote rate limited symbol={} reason={}", symbol, e.getMessage());
            return Optional.empty();
        }

        try {
            FinnhubQuote body = restClient.get()
                    .uri(b -> b.path("/quote").queryParam("symbol", symbol).build())
                    .header(AUTH_HEADER, properties.apiKey())
                    .retrieve()
                    .body(FinnhubQuote.class);
            if (body == null || !body.hasPrice()) {
                // 잘못된 심볼도 200 에 0 으로 온다. 조용히 0 원을 화면에 띄우지 않는다.
                log.warn("[FinnhubClient] quote 빈 응답 symbol={}", symbol);
                return Optional.empty();
            }
            return Optional.of(body);
        } catch (HttpClientErrorException.Unauthorized | HttpClientErrorException.Forbidden e) {
            log.error("[FinnhubClient] quote 인증 실패 — API 키 확인 필요 symbol={} status={}", symbol, e.getStatusCode());
            return Optional.empty();
        } catch (HttpClientErrorException.TooManyRequests e) {
            log.warn("[FinnhubClient] quote rate limit (429) symbol={}", symbol);
            return Optional.empty();
        } catch (RestClientException e) {
            log.warn("[FinnhubClient] quote 호출 실패 symbol={} reason={}", symbol, e.getMessage());
            return Optional.empty();
        }
    }

    /**
     * `/stock/earnings?symbol={ticker}` 호출. 최근 분기 어닝 결과 배열 반환 (Finnhub 기본 4분기).
     *
     * @return 응답이 비거나 호출이 실패하면 빈 List
     */
    public List<FinnhubEarningsRow> fetchEarningsHistory(String ticker,
                                                         FinnhubRateLimiter.Priority priority) {
        try {
            rateLimiter.acquire(priority);
        } catch (FinnhubRateLimitExceededException e) {
            log.warn("[FinnhubClient] earnings rate limited ticker={} priority={} reason={}",
                    ticker, priority, e.getMessage());
            return Collections.emptyList();
        }

        try {
            FinnhubEarningsRow[] body = restClient.get()
                    .uri(b -> b.path("/stock/earnings")
                            .queryParam("symbol", ticker)
                            .build())
                    .header(AUTH_HEADER, properties.apiKey())
                    .retrieve()
                    .body(FinnhubEarningsRow[].class);

            if (body == null || body.length == 0) {
                log.warn("[FinnhubClient] earnings empty response ticker={}", ticker);
                return Collections.emptyList();
            }
            return List.of(body);
        } catch (HttpClientErrorException.Unauthorized | HttpClientErrorException.Forbidden e) {
            log.error("[FinnhubClient] earnings 인증 실패 — API 키 확인 필요 ticker={} status={}",
                    ticker, e.getStatusCode());
            return Collections.emptyList();
        } catch (HttpClientErrorException.TooManyRequests e) {
            log.warn("[FinnhubClient] earnings rate limit (429) — 후속 호출 일시 자제 권장 ticker={}",
                    ticker);
            return Collections.emptyList();
        } catch (RestClientException e) {
            log.warn("[FinnhubClient] earnings 호출 실패 ticker={} reason={}",
                    ticker, e.getMessage());
            return Collections.emptyList();
        }
    }
}
