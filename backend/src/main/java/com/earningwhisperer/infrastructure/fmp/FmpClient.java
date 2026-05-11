package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.infrastructure.fmp.dto.FmpEarningsCalendarItem;
import com.earningwhisperer.infrastructure.fmp.dto.FmpHistoricalBar;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.time.LocalDate;
import java.util.Collections;
import java.util.List;
import java.util.Optional;

/**
 * FMP 외부 API 호출 클라이언트.
 *
 * <p>모든 호출은 {@link FmpRateLimiter#acquire(FmpRateLimiter.Priority)} 를 통해 게이팅된다.
 * 호출 실패(네트워크/4xx/5xx) 또는 rate limit 초과 시 빈 결과를 반환하고 WARN 로그만 남긴다 —
 * 호출자는 graceful fallback(예: 마지막 캐시값 유지) 을 수행할 수 있다.
 *
 * <p>FMP_API_KEY 미설정 시 Bean 미등록(@ConditionalOnExpression).
 */
@Component
@ConditionalOnExpression("!'${fmp.api-key:}'.isBlank()")
@Slf4j
public class FmpClient {

    private final RestClient restClient;
    private final FmpProperties properties;
    private final FmpRateLimiter rateLimiter;

    public FmpClient(@Qualifier("fmpRestClient") RestClient restClient,
                     FmpProperties properties,
                     FmpRateLimiter rateLimiter) {
        this.restClient = restClient;
        this.properties = properties;
        this.rateLimiter = rateLimiter;
    }

    /**
     * `/stable/profile?symbol={ticker}` 호출. 응답은 배열이지만 1건만 사용.
     *
     * <p>2025-08-31 이후 legacy `/v3/profile/{ticker}` 가 신규 사용자에게 403 으로 거부되어
     * `/stable/profile` 로 마이그레이션. 응답 schema 의 일부 필드명도 변경됨 (FmpProfile 참고).
     */
    public Optional<FmpProfile> fetchProfile(String ticker, FmpRateLimiter.Priority priority) {
        try {
            rateLimiter.acquire(priority);
        } catch (RateLimitExceededException e) {
            log.warn("[FmpClient] profile rate limited ticker={} priority={} reason={}",
                    ticker, priority, e.getMessage());
            return Optional.empty();
        }

        try {
            FmpProfile[] body = restClient.get()
                    .uri(b -> b.path("/stable/profile")
                            .queryParam("symbol", ticker)
                            .queryParam("apikey", properties.apiKey())
                            .build())
                    .retrieve()
                    .body(FmpProfile[].class);

            if (body == null || body.length == 0) {
                log.warn("[FmpClient] profile empty response ticker={}", ticker);
                return Optional.empty();
            }
            FmpProfile profile = body[0];
            // range 파싱 실패 시 silent empty 가 아닌 WARN 1건 — 운영 중 포맷 변화를 빠르게 감지한다.
            if (profile != null && profile.range() != null && profile.low52w().isEmpty()) {
                log.warn("[FmpClient] profile.range 파싱 실패 ticker={} raw='{}'",
                        ticker, profile.range());
            }
            return Optional.ofNullable(profile);
        } catch (HttpClientErrorException.Unauthorized | HttpClientErrorException.Forbidden e) {
            log.error("[FmpClient] profile 인증 실패 — API 키 확인 필요 ticker={} status={}",
                    ticker, e.getStatusCode());
            return Optional.empty();
        } catch (HttpClientErrorException.TooManyRequests e) {
            log.warn("[FmpClient] profile rate limit (429) — 후속 호출 일시 자제 권장 ticker={}", ticker);
            return Optional.empty();
        } catch (RestClientException e) {
            log.warn("[FmpClient] profile 호출 실패 ticker={} reason={}", ticker, e.getMessage());
            return Optional.empty();
        }
    }

    /**
     * `/stable/earnings-calendar?from=&to=` 호출. 날짜 범위 내 전 종목 어닝 일정 반환.
     */
    public List<FmpEarningsCalendarItem> fetchEarningsCalendar(LocalDate from, LocalDate to,
                                                               FmpRateLimiter.Priority priority) {
        try {
            rateLimiter.acquire(priority);
        } catch (RateLimitExceededException e) {
            log.warn("[FmpClient] earningsCalendar rate limited from={} to={} reason={}", from, to, e.getMessage());
            return Collections.emptyList();
        }

        try {
            FmpEarningsCalendarItem[] body = restClient.get()
                    .uri(b -> b.path("/stable/earnings-calendar")
                            .queryParam("from", from)
                            .queryParam("to", to)
                            .queryParam("apikey", properties.apiKey())
                            .build())
                    .retrieve()
                    .body(FmpEarningsCalendarItem[].class);

            if (body == null || body.length == 0) {
                log.warn("[FmpClient] earningsCalendar empty response from={} to={}", from, to);
                return Collections.emptyList();
            }
            return List.of(body);
        } catch (HttpClientErrorException.Unauthorized | HttpClientErrorException.Forbidden e) {
            log.error("[FmpClient] earningsCalendar 인증 실패 — API 키 확인 필요 status={}", e.getStatusCode());
            return Collections.emptyList();
        } catch (HttpClientErrorException.TooManyRequests e) {
            log.warn("[FmpClient] earningsCalendar rate limit (429) from={} to={}", from, to);
            return Collections.emptyList();
        } catch (RestClientException e) {
            log.warn("[FmpClient] earningsCalendar 호출 실패 from={} to={} reason={}", from, to, e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * `/stable/historical-price-eod/full?symbol={ticker}` 호출. date 내림차순 일봉 리스트 반환.
     *
     * <p>응답이 wrapper 없는 array 라 FmpHistoricalBar[] 로 직접 매핑한다.
     * timeseries 파라미터는 새 endpoint 에서 미지원 — 전체 히스토리가 내려오므로 클라이언트 측에서 days 만큼 자른다.
     *
     * <p>2025-08-31 이후 legacy `/v3/historical-price-full/{ticker}` 가 거부되어 마이그레이션.
     */
    public List<FmpHistoricalBar> fetchHistorical(String ticker, int days, FmpRateLimiter.Priority priority) {
        try {
            rateLimiter.acquire(priority);
        } catch (RateLimitExceededException e) {
            log.warn("[FmpClient] historical rate limited ticker={} priority={} reason={}",
                    ticker, priority, e.getMessage());
            return Collections.emptyList();
        }

        try {
            FmpHistoricalBar[] body = restClient.get()
                    .uri(b -> b.path("/stable/historical-price-eod/full")
                            .queryParam("symbol", ticker)
                            .queryParam("apikey", properties.apiKey())
                            .build())
                    .retrieve()
                    .body(FmpHistoricalBar[].class);

            if (body == null || body.length == 0) {
                log.warn("[FmpClient] historical empty response ticker={}", ticker);
                return Collections.emptyList();
            }
            if (body.length > days) {
                return List.of(java.util.Arrays.copyOfRange(body, 0, days));
            }
            return List.of(body);
        } catch (HttpClientErrorException.Unauthorized | HttpClientErrorException.Forbidden e) {
            log.error("[FmpClient] historical 인증 실패 — API 키 확인 필요 ticker={} status={}",
                    ticker, e.getStatusCode());
            return Collections.emptyList();
        } catch (HttpClientErrorException.TooManyRequests e) {
            log.warn("[FmpClient] historical rate limit (429) — 후속 호출 일시 자제 권장 ticker={}", ticker);
            return Collections.emptyList();
        } catch (RestClientException e) {
            log.warn("[FmpClient] historical 호출 실패 ticker={} reason={}", ticker, e.getMessage());
            return Collections.emptyList();
        }
    }
}
