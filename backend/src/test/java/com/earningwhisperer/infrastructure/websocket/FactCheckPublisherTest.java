package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.aiengine.LiveFactCheckModels;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * FactCheckPublisher 단위 테스트.
 *
 * 발행 조건(무엇을 내보내고 무엇을 거르는가)과 페이로드 직렬화 형식을 검증한다.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("FactCheckPublisher")
class FactCheckPublisherTest {

    @Mock SimpMessagingTemplate messagingTemplate;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private FactCheckPublisher publisher() {
        return new FactCheckPublisher(messagingTemplate);
    }

    private static LiveFactCheckModels.BatchResponse batch(String status,
                                                           List<LiveFactCheckModels.Claim> claims) {
        return new LiveFactCheckModels.BatchResponse(
                "ORCL", status, 0, 0, 2, claims, 1, true, true, List.of());
    }

    private static LiveFactCheckModels.Claim claim() {
        return new LiveFactCheckModels.Claim("ORCL:0-2:c1", 1, "원문", "정규화된 주장",
                "numeric_fact", "CONTRADICTED", 0.85, "매출 성장률은 52%가 아닌 42%입니다.",
                "contradicted_by_news",
                List.of(new LiveFactCheckModels.Evidence("d1", "제목", "발췌", "https://e.com/1",
                        "reuters", 1_788_000_000L, 0.91)),
                2, 2);
    }

    @Test
    @DisplayName("ticker 별 토픽으로 발행한다")
    void 토픽_경로() {
        publisher().publish("ORCL", "demo-1", batch("COMPLETED", List.of(claim())));

        verify(messagingTemplate).convertAndSend(eqTopic("/topic/factcheck/ORCL"), any(Object.class));
    }

    @Test
    @DisplayName("COMPLETED 가 아니면 발행하지 않는다")
    void 버퍼링은_미발행() {
        publisher().publish("ORCL", "demo-1", batch("BUFFERING", List.of()));

        verify(messagingTemplate, never()).convertAndSend(anyString(), any(Object.class));
    }

    @Test
    @DisplayName("주장이 0건이면 발행하지 않는다")
    void 빈_판정은_미발행() {
        // 추출 LLM 타임아웃 시 COMPLETED + claims=[] 로 돌아온다. 화면에 그릴 것이 없다.
        publisher().publish("ORCL", "demo-1", batch("COMPLETED", List.of()));

        verify(messagingTemplate, never()).convertAndSend(anyString(), any(Object.class));
    }

    @Test
    @DisplayName("null 배치도 예외 없이 무시한다")
    void null_배치() {
        publisher().publish("ORCL", "demo-1", null);

        verify(messagingTemplate, never()).convertAndSend(anyString(), any(Object.class));
    }

    @Test
    @DisplayName("STOMP 발행 실패가 호출자로 전파되지 않는다")
    void 발행_실패_흡수() {
        // 팩트체크 카드 한 장 때문에 재생 루프가 멈추면 안 된다.
        org.mockito.Mockito.doThrow(new IllegalStateException("broker down"))
                .when(messagingTemplate).convertAndSend(anyString(), any(Object.class));

        publisher().publish("ORCL", "demo-1", batch("COMPLETED", List.of(claim())));
    }

    @Test
    @DisplayName("페이로드 키가 계약대로 snake_case 로 직렬화된다")
    void 직렬화_형식() throws Exception {
        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        publisher().publish("ORCL", "demo-1", batch("COMPLETED", List.of(claim())));
        verify(messagingTemplate).convertAndSend(anyString(), captor.capture());

        JsonNode json = objectMapper.valueToTree(captor.getValue());

        assertThat(json.get("ticker").asText()).isEqualTo("ORCL");
        assertThat(json.get("call_id").asText()).isEqualTo("demo-1");
        assertThat(json.get("batch_start_sequence").asInt()).isZero();
        assertThat(json.get("batch_end_sequence").asInt()).isEqualTo(2);
        assertThat(json.get("claims")).hasSize(1);

        JsonNode claim = json.get("claims").get(0);
        assertThat(claim.get("claim_id").asText()).isEqualTo("ORCL:0-2:c1");
        assertThat(claim.get("verdict").asText()).isEqualTo("CONTRADICTED");
        assertThat(claim.get("explanation_ko").asText()).isNotBlank();
        assertThat(claim.get("reason_code").asText()).isEqualTo("contradicted_by_news");
        assertThat(claim.get("evidence").get(0).get("doc_id").asText()).isEqualTo("d1");
        assertThat(claim.get("evidence").get(0).get("relevance_score").asDouble()).isEqualTo(0.91);
    }

    private static String eqTopic(String topic) {
        return org.mockito.ArgumentMatchers.eq(topic);
    }
}
