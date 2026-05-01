package com.earningwhisperer.infrastructure.finnhub;

import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubCalendarRow;
import com.earningwhisperer.infrastructure.finnhub.dto.FinnhubEarningsRow;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestToUriTemplate;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * FinnhubClient 단위 테스트.
 *
 * <p>MockRestServiceServer 로 외부 호출을 stub. RateLimiter 는 실 객체를 사용하되
 * 테스트 종료 시 shutdown.
 */
@DisplayName("FinnhubClient 단위 테스트")
class FinnhubClientTest {

    private static final String BASE_URL = "https://finnhub.io/api/v1";
    private static final String API_KEY = "test-finnhub-key";

    private MockRestServiceServer server;
    private FinnhubRateLimiter rateLimiter;
    private FinnhubClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
        server = MockRestServiceServer.bindTo(builder).build();
        RestClient restClient = builder.build();
        FinnhubProperties properties = new FinnhubProperties(BASE_URL, API_KEY);
        rateLimiter = new FinnhubRateLimiter(null);
        client = new FinnhubClient(restClient, properties, rateLimiter);
    }

    @AfterEach
    void tearDown() {
        rateLimiter.shutdown();
    }

    @Test
    @DisplayName("fetchCalendar 정상 응답 → 파싱된 row 반환, X-Finnhub-Token 헤더 포함")
    void fetchCalendar_정상() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/calendar/earnings?from={from}&to={to}",
                        "2026-05-01", "2026-05-31"))
                .andExpect(method(org.springframework.http.HttpMethod.GET))
                .andExpect(header("X-Finnhub-Token", API_KEY))
                .andRespond(withSuccess(
                        "{"
                                + "\"earningsCalendar\": ["
                                + "  {\"symbol\": \"AAPL\", \"date\": \"2026-05-02\", \"hour\": \"amc\","
                                + "   \"epsEstimate\": 1.42, \"revenueEstimate\": 90000000000},"
                                + "  {\"symbol\": \"MSFT\", \"date\": \"2026-05-15\", \"hour\": \"bmo\"}"
                                + "]}",
                        MediaType.APPLICATION_JSON));

        List<FinnhubCalendarRow> rows = client.fetchCalendar(
                LocalDate.of(2026, 5, 1),
                LocalDate.of(2026, 5, 31),
                FinnhubRateLimiter.Priority.LOW);

        assertThat(rows).hasSize(2);
        assertThat(rows.get(0).symbol()).isEqualTo("AAPL");
        assertThat(rows.get(0).date()).isEqualTo(LocalDate.of(2026, 5, 2));
        assertThat(rows.get(0).hour()).isEqualTo("amc");
        assertThat(rows.get(0).epsEstimate()).isNotNull();
        assertThat(rows.get(1).symbol()).isEqualTo("MSFT");
        server.verify();
    }

    @Test
    @DisplayName("fetchCalendar 5xx 응답 → 빈 리스트 반환 (graceful)")
    void fetchCalendar_5xx_빈리스트() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/calendar/earnings?from={from}&to={to}",
                        "2026-05-01", "2026-05-31"))
                .andRespond(withServerError());

        List<FinnhubCalendarRow> rows = client.fetchCalendar(
                LocalDate.of(2026, 5, 1),
                LocalDate.of(2026, 5, 31),
                FinnhubRateLimiter.Priority.LOW);

        assertThat(rows).isEmpty();
        server.verify();
    }

    @Test
    @DisplayName("fetchEarningsHistory 정상 응답 → 파싱된 row 반환")
    void fetchEarningsHistory_정상() {
        server.expect(requestToUriTemplate(
                        BASE_URL + "/stock/earnings?symbol={symbol}", "AAPL"))
                .andExpect(method(org.springframework.http.HttpMethod.GET))
                .andExpect(header("X-Finnhub-Token", API_KEY))
                .andRespond(withSuccess(
                        "["
                                + "{\"actual\": 1.88, \"estimate\": 1.43, \"period\": \"2025-09-28\","
                                + " \"quarter\": 3, \"surprise\": 0.45, \"surprisePercent\": 31.4685,"
                                + " \"symbol\": \"AAPL\", \"year\": 2025},"
                                + "{\"actual\": 1.50, \"estimate\": 1.50, \"period\": \"2025-06-29\","
                                + " \"quarter\": 2, \"surprise\": 0.00, \"surprisePercent\": 0.0,"
                                + " \"symbol\": \"AAPL\", \"year\": 2025}"
                                + "]",
                        MediaType.APPLICATION_JSON));

        List<FinnhubEarningsRow> rows = client.fetchEarningsHistory(
                "AAPL", FinnhubRateLimiter.Priority.HIGH);

        assertThat(rows).hasSize(2);
        FinnhubEarningsRow first = rows.get(0);
        assertThat(first.symbol()).isEqualTo("AAPL");
        assertThat(first.period()).isEqualTo(LocalDate.of(2025, 9, 28));
        assertThat(first.epsActual()).isNotNull();
        assertThat(first.epsEstimate()).isNotNull();
        assertThat(first.surprise()).isNotNull();
        assertThat(first.quarter()).isEqualTo(3);
        assertThat(first.quarterLabel()).isEqualTo("Q3");
        server.verify();
    }
}
