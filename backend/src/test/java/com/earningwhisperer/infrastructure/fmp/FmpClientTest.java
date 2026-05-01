package com.earningwhisperer.infrastructure.fmp;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.earningwhisperer.infrastructure.fmp.dto.FmpHistoricalBar;
import com.earningwhisperer.infrastructure.fmp.dto.FmpProfile;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.time.Clock;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestToUriTemplate;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * FmpClient 단위 테스트.
 *
 * <p>MockRestServiceServer 로 외부 호출을 stub. RateLimiter 는 실 객체를 사용하되 Redis 는 mock.
 * 4xx/5xx 분기, days 자르기, range 파싱 WARN 검증.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("FmpClient 단위 테스트")
class FmpClientTest {

    private static final String BASE_URL = "https://financialmodelingprep.com/api";
    private static final String API_KEY = "test-fmp-key";

    private MockRestServiceServer server;
    private FmpRateLimiter rateLimiter;
    private FmpClient client;

    private Logger clientLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
        server = MockRestServiceServer.bindTo(builder).build();
        RestClient restClient = builder.build();
        FmpProperties properties = new FmpProperties(BASE_URL, API_KEY);

        @SuppressWarnings("unchecked")
        RedisTemplate<String, String> redisTemplate = mock(RedisTemplate.class);
        AtomicLong counter = new AtomicLong(0);
        lenient().when(redisTemplate.execute(
                        any(RedisScript.class),
                        any(List.class),
                        any(Object[].class)))
                .thenAnswer(inv -> counter.incrementAndGet());

        rateLimiter = new FmpRateLimiter(redisTemplate, Clock.systemUTC(), null);
        client = new FmpClient(restClient, properties, rateLimiter);

        // logback ListAppender — 로그 레벨 분기 검증
        clientLogger = (Logger) LoggerFactory.getLogger(FmpClient.class);
        appender = new ListAppender<>();
        appender.start();
        clientLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        clientLogger.detachAppender(appender);
        rateLimiter.shutdown();
    }

    @Test
    @DisplayName("fetchProfile 정상 응답 → FmpProfile 1건 반환, range 파싱 성공")
    void fetchProfile_정상() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/profile/{ticker}?apikey={apiKey}",
                        "AAPL", API_KEY))
                .andExpect(method(org.springframework.http.HttpMethod.GET))
                .andRespond(withSuccess(
                        "[{\"symbol\":\"AAPL\",\"companyName\":\"Apple Inc.\","
                                + "\"sector\":\"Technology\",\"price\":175.0,"
                                + "\"range\":\"75.60-138.07\"}]",
                        MediaType.APPLICATION_JSON));

        Optional<FmpProfile> result = client.fetchProfile("AAPL", FmpRateLimiter.Priority.HIGH);

        assertThat(result).isPresent();
        assertThat(result.get().symbol()).isEqualTo("AAPL");
        assertThat(result.get().low52w()).hasValue(new java.math.BigDecimal("75.60"));
        // range 파싱 성공 — WARN 로그 없어야 함
        assertThat(appender.list).noneMatch(e ->
                e.getLevel() == Level.WARN && e.getFormattedMessage().contains("range 파싱 실패"));
        server.verify();
    }

    @Test
    @DisplayName("fetchProfile 401 → ERROR 로그 + Optional.empty (인증 실패 분기)")
    void fetchProfile_401_인증실패() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/profile/{ticker}?apikey={apiKey}",
                        "AAPL", API_KEY))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED));

        Optional<FmpProfile> result = client.fetchProfile("AAPL", FmpRateLimiter.Priority.HIGH);

        assertThat(result).isEmpty();
        assertThat(appender.list).anyMatch(e ->
                e.getLevel() == Level.ERROR && e.getFormattedMessage().contains("인증 실패"));
        server.verify();
    }

    @Test
    @DisplayName("fetchProfile 403 → ERROR 로그 + Optional.empty (인증 실패 분기)")
    void fetchProfile_403_인증실패() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/profile/{ticker}?apikey={apiKey}",
                        "AAPL", API_KEY))
                .andRespond(withStatus(HttpStatus.FORBIDDEN));

        Optional<FmpProfile> result = client.fetchProfile("AAPL", FmpRateLimiter.Priority.HIGH);

        assertThat(result).isEmpty();
        assertThat(appender.list).anyMatch(e ->
                e.getLevel() == Level.ERROR && e.getFormattedMessage().contains("인증 실패"));
        server.verify();
    }

    @Test
    @DisplayName("fetchProfile 429 → WARN 로그 + Optional.empty (rate limit 분기)")
    void fetchProfile_429_rate_limit() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/profile/{ticker}?apikey={apiKey}",
                        "AAPL", API_KEY))
                .andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS));

        Optional<FmpProfile> result = client.fetchProfile("AAPL", FmpRateLimiter.Priority.HIGH);

        assertThat(result).isEmpty();
        assertThat(appender.list).anyMatch(e ->
                e.getLevel() == Level.WARN && e.getFormattedMessage().contains("rate limit (429)"));
        // 인증 실패 ERROR 로그는 없어야 함
        assertThat(appender.list).noneMatch(e ->
                e.getLevel() == Level.ERROR && e.getFormattedMessage().contains("인증 실패"));
        server.verify();
    }

    @Test
    @DisplayName("fetchProfile 5xx → WARN 로그 + Optional.empty (일반 분기)")
    void fetchProfile_5xx() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/profile/{ticker}?apikey={apiKey}",
                        "AAPL", API_KEY))
                .andRespond(withServerError());

        Optional<FmpProfile> result = client.fetchProfile("AAPL", FmpRateLimiter.Priority.HIGH);

        assertThat(result).isEmpty();
        assertThat(appender.list).anyMatch(e ->
                e.getLevel() == Level.WARN && e.getFormattedMessage().contains("호출 실패"));
        server.verify();
    }

    @Test
    @DisplayName("fetchProfile range 파싱 실패 시 WARN 로그 1건")
    void fetchProfile_range_파싱_실패_WARN() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/profile/{ticker}?apikey={apiKey}",
                        "AAPL", API_KEY))
                .andRespond(withSuccess(
                        "[{\"symbol\":\"AAPL\",\"companyName\":\"Apple Inc.\","
                                + "\"range\":\"INVALID-FORMAT\"}]",
                        MediaType.APPLICATION_JSON));

        Optional<FmpProfile> result = client.fetchProfile("AAPL", FmpRateLimiter.Priority.HIGH);

        assertThat(result).isPresent();
        assertThat(result.get().low52w()).isEmpty();
        assertThat(appender.list).anyMatch(e ->
                e.getLevel() == Level.WARN
                        && e.getFormattedMessage().contains("range 파싱 실패")
                        && e.getFormattedMessage().contains("INVALID-FORMAT"));
        server.verify();
    }

    @Test
    @DisplayName("fetchHistorical 정상 응답 → 파싱된 bar 리스트 반환")
    void fetchHistorical_정상() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/historical-price-full/{ticker}?timeseries={days}&apikey={apiKey}",
                        "AAPL", 5, API_KEY))
                .andRespond(withSuccess(
                        "{\"symbol\":\"AAPL\",\"historical\":["
                                + "{\"date\":\"2026-04-30\",\"close\":175.0,\"volume\":50000000},"
                                + "{\"date\":\"2026-04-29\",\"close\":174.5,\"volume\":48000000}"
                                + "]}",
                        MediaType.APPLICATION_JSON));

        List<FmpHistoricalBar> bars = client.fetchHistorical("AAPL", 5, FmpRateLimiter.Priority.LOW);

        assertThat(bars).hasSize(2);
        assertThat(bars.get(0).close()).isEqualTo(new java.math.BigDecimal("175.0"));
        server.verify();
    }

    @Test
    @DisplayName("fetchHistorical — 응답이 days 보다 많을 때 days 만큼만 자르기")
    void fetchHistorical_days_자르기() {
        // days=2 요청, 응답 4건 → 앞 2건만 반환
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/historical-price-full/{ticker}?timeseries={days}&apikey={apiKey}",
                        "AAPL", 2, API_KEY))
                .andRespond(withSuccess(
                        "{\"symbol\":\"AAPL\",\"historical\":["
                                + "{\"date\":\"2026-04-30\",\"close\":175.0,\"volume\":1},"
                                + "{\"date\":\"2026-04-29\",\"close\":174.5,\"volume\":2},"
                                + "{\"date\":\"2026-04-28\",\"close\":174.0,\"volume\":3},"
                                + "{\"date\":\"2026-04-27\",\"close\":173.5,\"volume\":4}"
                                + "]}",
                        MediaType.APPLICATION_JSON));

        List<FmpHistoricalBar> bars = client.fetchHistorical("AAPL", 2, FmpRateLimiter.Priority.LOW);

        assertThat(bars).hasSize(2);
        assertThat(bars.get(0).volume()).isEqualTo(1L);
        assertThat(bars.get(1).volume()).isEqualTo(2L);
        server.verify();
    }

    @Test
    @DisplayName("fetchHistorical 5xx → 빈 List + WARN")
    void fetchHistorical_5xx() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/historical-price-full/{ticker}?timeseries={days}&apikey={apiKey}",
                        "AAPL", 5, API_KEY))
                .andRespond(withServerError());

        List<FmpHistoricalBar> bars = client.fetchHistorical("AAPL", 5, FmpRateLimiter.Priority.LOW);

        assertThat(bars).isEmpty();
        assertThat(appender.list).anyMatch(e ->
                e.getLevel() == Level.WARN && e.getFormattedMessage().contains("호출 실패"));
        server.verify();
    }

    @Test
    @DisplayName("fetchHistorical 401 → ERROR 로그 + 빈 List")
    void fetchHistorical_401() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/v3/historical-price-full/{ticker}?timeseries={days}&apikey={apiKey}",
                        "AAPL", 5, API_KEY))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED));

        List<FmpHistoricalBar> bars = client.fetchHistorical("AAPL", 5, FmpRateLimiter.Priority.LOW);

        assertThat(bars).isEmpty();
        assertThat(appender.list).anyMatch(e ->
                e.getLevel() == Level.ERROR && e.getFormattedMessage().contains("인증 실패"));
        server.verify();
    }
}
