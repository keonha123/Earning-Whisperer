package com.earningwhisperer.infrastructure.assistant;

import com.earningwhisperer.domain.assistant.AssistantAskService.PreparedAsk;
import com.earningwhisperer.global.config.AssistantProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * logothea-assistant {@code POST /v1/assistant/ask}(api-spec 10.6) 호출. 응답 SSE 본문을 그대로 돌려주고,
 * 읽기·닫기는 중계(AssistantRelay)가 맡는다. 본문을 닫으면 연결이 끊겨 assistant 쪽 생성도 멈춘다.
 */
@Component
public class AssistantStreamClient {

    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(3);
    // 응답 헤더까지의 상한. 본문 스트림 전체는 SseEmitter 타임아웃이 묶는다.
    private static final Duration RESPONSE_HEADERS_TIMEOUT = Duration.ofSeconds(10);

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final URI askUri;
    private final String internalSecret;

    @Autowired
    public AssistantStreamClient(AssistantProperties properties, ObjectMapper objectMapper,
                                 @Value("${app.internal.secret:}") String internalSecret) {
        // HTTP/1.1 로 고정한다. 기본값(HTTP/2)은 평문 연결에서 h2c 업그레이드를 시도해 uvicorn 과 불필요하게 협상한다.
        this.httpClient = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(CONNECT_TIMEOUT).build();
        this.objectMapper = objectMapper;
        this.askUri = URI.create(properties.baseUrl().replaceAll("/+$", "") + "/v1/assistant/ask");
        this.internalSecret = internalSecret;
    }

    public InputStream open(PreparedAsk ask) throws AssistantUnavailableException {
        HttpRequest request = HttpRequest.newBuilder(askUri)
                .timeout(RESPONSE_HEADERS_TIMEOUT)
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream")
                .header("X-Internal-Secret", internalSecret)
                .POST(HttpRequest.BodyPublishers.ofString(toJson(ask), StandardCharsets.UTF_8))
                .build();
        HttpResponse<InputStream> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
        } catch (IOException e) {
            throw new AssistantUnavailableException("connect_failed", e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssistantUnavailableException("interrupted", e);
        }
        if (response.statusCode() != 200) {
            closeQuietly(response.body());
            throw new AssistantUnavailableException("http_" + response.statusCode());
        }
        return response.body();
    }

    private String toJson(PreparedAsk ask) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("user_id", String.valueOf(ask.userId()));
        body.put("ticker", ask.ticker());
        body.put("call_id", ask.callId());
        body.put("as_of_sequence", ask.asOfSequence());
        body.put("as_of_epoch", ask.asOfEpoch());
        body.put("anchor_sequence", ask.anchorSequence());
        body.put("call_ended", ask.callEnded());
        body.put("question", ask.question());
        body.put("suggested_question_id", ask.suggestedQuestionId());
        List<Map<String, String>> history = ask.history().stream()
                .map(turn -> Map.of("role", turn.role(), "text", turn.text()))
                .toList();
        body.put("history", history);
        try {
            return objectMapper.writeValueAsString(body);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("질의응답 요청을 직렬화하지 못했습니다", e);
        }
    }

    private static void closeQuietly(InputStream in) {
        try {
            in.close();
        } catch (IOException ignored) {
            // 실패 응답의 본문이라 닫기 실패는 의미가 없다.
        }
    }
}
