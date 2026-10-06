package com.earningwhisperer.infrastructure.assistant;

import com.earningwhisperer.domain.assistant.AssistantAskService.HistoryTurn;
import com.earningwhisperer.domain.assistant.AssistantAskService.PreparedAsk;
import com.earningwhisperer.global.config.AssistantProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("AssistantStreamClient")
class AssistantStreamClientTest {

    private HttpServer server;
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final AtomicReference<String> body = new AtomicReference<>();
    private final AtomicReference<String> secret = new AtomicReference<>();
    private final AtomicReference<String> accept = new AtomicReference<>();
    private volatile int status = 200;

    @BeforeEach
    void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/assistant/ask", exchange -> {
            body.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            secret.set(exchange.getRequestHeaders().getFirst("X-Internal-Secret"));
            accept.set(exchange.getRequestHeaders().getFirst("Accept"));
            byte[] payload = "event: done\ndata: {}\n\n".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(status, payload.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(payload);
            }
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private AssistantStreamClient client(String baseUrl) {
        return new AssistantStreamClient(new AssistantProperties(baseUrl, 50, 60), objectMapper, "s3cret");
    }

    private static PreparedAsk ask() {
        return new PreparedAsk(7L, "WMT", "call-1", 17, 1_787_227_218L, null, true, "요약해 줘", "summary",
                List.of(new HistoryTurn("user", "앞 질문")));
    }

    @Test
    @DisplayName("snake_case 본문과 내부 비밀 헤더로 보내고 SSE 본문을 돌려준다")
    void sendsRequest() throws Exception {
        String baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();

        try (InputStream in = client(baseUrl).open(ask())) {
            assertThat(new String(in.readAllBytes(), StandardCharsets.UTF_8)).isEqualTo("event: done\ndata: {}\n\n");
        }

        assertThat(secret.get()).isEqualTo("s3cret");
        assertThat(accept.get()).isEqualTo("text/event-stream");
        JsonNode json = objectMapper.readTree(body.get());
        assertThat(json.get("user_id").asText()).isEqualTo("7");
        assertThat(json.get("user_id").isTextual()).isTrue();
        assertThat(json.get("ticker").asText()).isEqualTo("WMT");
        assertThat(json.get("call_id").asText()).isEqualTo("call-1");
        assertThat(json.get("as_of_sequence").asInt()).isEqualTo(17);
        assertThat(json.get("as_of_epoch").asLong()).isEqualTo(1_787_227_218L);
        assertThat(json.get("anchor_sequence").isNull()).isTrue();
        assertThat(json.get("call_ended").asBoolean()).isTrue();
        assertThat(json.get("question").asText()).isEqualTo("요약해 줘");
        assertThat(json.get("suggested_question_id").asText()).isEqualTo("summary");
        assertThat(json.get("history").get(0).get("role").asText()).isEqualTo("user");
        assertThat(json.get("history").get(0).get("text").asText()).isEqualTo("앞 질문");
    }

    @Test
    @DisplayName("200 이 아니면 http_<status>")
    void nonOkStatus() {
        status = 401;
        String baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();

        assertThatThrownBy(() -> client(baseUrl).open(ask()))
                .isInstanceOf(AssistantUnavailableException.class)
                .hasMessage("http_401");
    }

    @Test
    @DisplayName("연결할 수 없으면 connect_failed")
    void connectFailed() {
        int port = server.getAddress().getPort();
        server.stop(0);

        assertThatThrownBy(() -> client("http://127.0.0.1:" + port).open(ask()))
                .isInstanceOf(AssistantUnavailableException.class)
                .hasMessage("connect_failed");
    }

    @Test
    @DisplayName("설정이 비어 있으면 기본값을 쓴다")
    void propertyDefaults() {
        AssistantProperties properties = new AssistantProperties(null, 0, 0);
        assertThat(properties.baseUrl()).isEqualTo("http://127.0.0.1:8100");
        assertThat(properties.dailyLimit()).isEqualTo(50);
        assertThat(properties.streamTimeoutSeconds()).isEqualTo(60);
    }
}
