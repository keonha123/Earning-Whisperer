package com.earningwhisperer.infrastructure.fmp;

import com.earningwhisperer.infrastructure.fmp.dto.FmpHistoricalBar;
import com.earningwhisperer.infrastructure.fmp.dto.FmpHistoricalResponse;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

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
     * `/v3/profile/{ticker}` 호출. 응답은 배열이지만 1건만 사용.
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
                    .uri(b -> b.path("/v3/profile/{ticker}")
                            .queryParam("apikey", properties.apiKey())
                            .build(ticker))
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
     * `/v3/historical-price-full/{ticker}?timeseries={days}` 호출. date 내림차순 일봉 리스트 반환.
     *
     * <p>FMP timeseries 파라미터가 무시되거나 더 많은 항목이 반환될 수 있으므로 클라이언트 측에서 days 만큼만 잘라 반환한다.
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
            FmpHistoricalResponse body = restClient.get()
                    .uri(b -> b.path("/v3/historical-price-full/{ticker}")
                            .queryParam("timeseries", days)
                            .queryParam("apikey", properties.apiKey())
                            .build(ticker))
                    .retrieve()
                    .body(FmpHistoricalResponse.class);

            if (body == null || body.historical() == null || body.historical().isEmpty()) {
                log.warn("[FmpClient] historical empty response ticker={}", ticker);
                return Collections.emptyList();
            }
            List<FmpHistoricalBar> historical = body.historical();
            if (historical.size() > days) {
                return List.copyOf(historical.subList(0, days));
            }
            return List.copyOf(historical);
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
