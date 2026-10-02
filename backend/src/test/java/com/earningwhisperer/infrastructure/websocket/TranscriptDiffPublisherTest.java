package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.infrastructure.aiengine.TranscriptDiffModels;
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
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * TranscriptDiffPublisher 단위 테스트.
 *
 * 발행 조건과 페이로드 직렬화 형식을 검증한다. 특히 <b>보여줄 것이 없는 응답</b>을
 * 거르는지가 중요하다 — 대부분의 발언은 주제와 무관해 항목이 비어서 돌아온다.
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("TranscriptDiffPublisher")
class TranscriptDiffPublisherTest {

    @Mock SimpMessagingTemplate messagingTemplate;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private TranscriptDiffPublisher publisher() {
        return new TranscriptDiffPublisher(messagingTemplate);
    }

    private static TranscriptDiffModels.PreviousDocument previous() {
        return new TranscriptDiffModels.PreviousDocument(
                "factset:WMT:wmt-fy27q1-2026-05-21",
                "Walmart, Inc. (WMT) Q1 FY2027 Earnings Call",
                "2026-05-21", "FY2027Q1", null);
    }

    private static TranscriptDiffModels.DiffItem item() {
        return new TranscriptDiffModels.DiffItem(
                "guidance", "improved",
                "직전 콜에서는 연간 가이던스를 유지한다고 했으나 이번에는 상향했습니다.",
                "We're raising our fiscal year sales guidance to 4% to 5%.",
                "We are reiterating our full year guidance of constant currency sales growth between 3.5% and 4.5%.",
                0.82, 0.25,
                List.of(new TranscriptDiffModels.Evidence(
                        "factset:WMT:wmt-fy27q1-2026-05-21", "factset",
                        "Walmart, Inc. (WMT) Q1 FY2027 Earnings Call", "2026-05-21", null,
                        "We are reiterating our full year guidance...", 0.72, 0.68)));
    }

    private static TranscriptDiffModels.DiffResponse response(boolean available,
                                                              List<TranscriptDiffModels.DiffItem> items,
                                                              List<String> warnings) {
        return new TranscriptDiffModels.DiffResponse(available, "WMT", previous(), items, warnings);
    }

    @Test
    @DisplayName("ticker 별 토픽으로 발행한다")
    void 토픽_경로() {
        publisher().publish("WMT", "demo-1", 22, response(true, List.of(item()), List.of()));

        verify(messagingTemplate).convertAndSend(eq("/topic/transcript-diff/WMT"), any(Object.class));
    }

    @Test
    @DisplayName("주제와 무관한 발언은 발행하지 않는다")
    void 항목이_비면_미발행() {
        // 대부분의 발언이 여기에 해당한다. 그릴 것이 없는데 카드를 띄우면 빈 카드만 쌓인다.
        publisher().publish("WMT", "demo-1", 3,
                response(true, List.of(), List.of("current_chunk_not_material")));

        verify(messagingTemplate, never()).convertAndSend(anyString(), any(Object.class));
    }

    @Test
    @DisplayName("직전 콜을 찾지 못하면 발행하지 않는다")
    void 대조_불가는_미발행() {
        publisher().publish("WMT", "demo-1", 3,
                response(false, List.of(), List.of("previous_transcript_not_found")));

        verify(messagingTemplate, never()).convertAndSend(anyString(), any(Object.class));
    }

    @Test
    @DisplayName("null 응답도 예외 없이 무시한다")
    void null_응답() {
        publisher().publish("WMT", "demo-1", 3, null);

        verify(messagingTemplate, never()).convertAndSend(anyString(), any(Object.class));
    }

    @Test
    @DisplayName("STOMP 발행 실패가 호출자로 전파되지 않는다")
    void 발행_실패_흡수() {
        org.mockito.Mockito.doThrow(new IllegalStateException("broker down"))
                .when(messagingTemplate).convertAndSend(anyString(), any(Object.class));

        publisher().publish("WMT", "demo-1", 22, response(true, List.of(item()), List.of()));
    }

    @Test
    @DisplayName("페이로드 키가 snake_case 로 직렬화된다")
    void 직렬화_형식() {
        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        publisher().publish("WMT", "demo-1", 22, response(true, List.of(item()), List.of()));
        verify(messagingTemplate).convertAndSend(anyString(), captor.capture());

        JsonNode json = objectMapper.valueToTree(captor.getValue());

        assertThat(json.get("ticker").asText()).isEqualTo("WMT");
        assertThat(json.get("call_id").asText()).isEqualTo("demo-1");
        assertThat(json.get("sequence").asInt()).isEqualTo(22);
        assertThat(json.get("previous_document").get("fiscal_quarter").asText()).isEqualTo("FY2027Q1");
        assertThat(json.get("items")).hasSize(1);

        JsonNode item = json.get("items").get(0);
        assertThat(item.get("change_type").asText()).isEqualTo("improved");
        assertThat(item.get("summary_ko").asText()).isNotBlank();
        assertThat(item.get("prior_claim").asText()).contains("3.5% and 4.5%");
        assertThat(item.get("risk_score").asDouble()).isEqualTo(0.25);
        assertThat(item.get("evidence").get(0).get("relevance_score").asDouble()).isEqualTo(0.72);
    }
}
