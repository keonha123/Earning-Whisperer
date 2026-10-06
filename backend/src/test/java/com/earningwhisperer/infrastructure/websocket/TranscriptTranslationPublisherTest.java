package com.earningwhisperer.infrastructure.websocket;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.MessagingException;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("TranscriptTranslationPublisher")
class TranscriptTranslationPublisherTest {

    @Mock SimpMessagingTemplate messagingTemplate;

    private static TranscriptTranslationPublisher.Payload payload() {
        return TranscriptTranslationPublisher.Payload.builder()
                .ticker("WMT")
                .callId("demo-1")
                .sequences(List.of(3, 4, 5))
                .textKo("Walmart U.S.의 기존점 매출은 2.6%였습니다.")
                .termsUsed(List.of("Comp sales"))
                .build();
    }

    @Test
    @DisplayName("종목별 토픽으로 snake_case 페이로드를 발행한다")
    void 발행() throws Exception {
        new TranscriptTranslationPublisher(messagingTemplate).publish(payload());

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(messagingTemplate).convertAndSend(eq("/topic/transcript-translation/WMT"), captor.capture());
        JsonNode json = new ObjectMapper().valueToTree(captor.getValue());
        assertThat(json.get("ticker").asText()).isEqualTo("WMT");
        assertThat(json.get("call_id").asText()).isEqualTo("demo-1");
        assertThat(json.get("sequences")).hasSize(3);
        assertThat(json.get("text_ko").asText()).startsWith("Walmart");
        assertThat(json.get("terms_used").get(0).asText()).isEqualTo("Comp sales");
    }

    @Test
    @DisplayName("발행 실패는 예외로 새지 않는다")
    void 발행_실패() {
        doThrow(new MessagingException("broker down")).when(messagingTemplate).convertAndSend(anyString(), any(Object.class));

        assertThatCode(() -> new TranscriptTranslationPublisher(messagingTemplate).publish(payload()))
                .doesNotThrowAnyException();
    }
}
