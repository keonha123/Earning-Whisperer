package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.domain.transcript.TranscriptSegment;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.MessagingException;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;

/**
 * TranscriptPublisher 단위 테스트.
 *
 * 검증 포인트:
 *   1) /topic/transcript/{ticker} 토픽으로 fan-out
 *   2) Contract 6.4 / 4.5 9필드 페이로드 + snake_case 직렬화
 *   3) speaker null 시 직렬화 제외
 *   4) STOMP 전송 실패 예외 흡수 (재던지지 않음)
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("TranscriptPublisher 단위 테스트")
class TranscriptPublisherTest {

    @Mock
    private SimpMessagingTemplate messagingTemplate;

    @InjectMocks
    private TranscriptPublisher publisher;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final TranscriptSegment SEGMENT = new TranscriptSegment(
            "NVDA", "earnings-2026Q1-NVDA", 42,
            120000L, 122500L,
            "Revenue grew strongly this quarter.",
            "CEO Jensen Huang", 1745000000L, false);

    @Test
    @DisplayName("publish — /topic/transcript/{ticker} 토픽으로 전송된다")
    void publish_올바른_토픽으로_전송됨() {
        publisher.publish(SEGMENT);

        ArgumentCaptor<String> dest = ArgumentCaptor.forClass(String.class);
        verify(messagingTemplate).convertAndSend(dest.capture(), any(Object.class));

        assertThat(dest.getValue()).isEqualTo("/topic/transcript/NVDA");
    }

    @Test
    @DisplayName("publish — 페이로드 9필드가 모두 도메인 값과 일치한다")
    void publish_페이로드_9필드_일치() {
        publisher.publish(SEGMENT);

        ArgumentCaptor<TranscriptPublisher.Payload> cap = ArgumentCaptor.forClass(TranscriptPublisher.Payload.class);
        verify(messagingTemplate).convertAndSend(eq("/topic/transcript/NVDA"), cap.capture());

        TranscriptPublisher.Payload p = cap.getValue();
        assertThat(p.getTicker()).isEqualTo("NVDA");
        assertThat(p.getCallId()).isEqualTo("earnings-2026Q1-NVDA");
        assertThat(p.getSequence()).isEqualTo(42);
        assertThat(p.getStartMs()).isEqualTo(120000L);
        assertThat(p.getEndMs()).isEqualTo(122500L);
        assertThat(p.getText()).isEqualTo("Revenue grew strongly this quarter.");
        assertThat(p.getSpeaker()).isEqualTo("CEO Jensen Huang");
        assertThat(p.getTimestamp()).isEqualTo(1745000000L);
        assertThat(p.isSessionEnd()).isFalse();
    }

    @Test
    @DisplayName("publish — JSON 직렬화 시 snake_case 보장 + 9필드 모두 포함")
    void publish_JSON_snake_case_검증() throws Exception {
        publisher.publish(SEGMENT);

        ArgumentCaptor<TranscriptPublisher.Payload> cap = ArgumentCaptor.forClass(TranscriptPublisher.Payload.class);
        verify(messagingTemplate).convertAndSend(eq("/topic/transcript/NVDA"), cap.capture());

        String json = objectMapper.writeValueAsString(cap.getValue());

        // snake_case 보장
        assertThat(json).contains("\"call_id\"");
        assertThat(json).contains("\"start_ms\"");
        assertThat(json).contains("\"end_ms\"");
        assertThat(json).contains("\"is_session_end\"");
        assertThat(json).doesNotContain("\"callId\"");
        assertThat(json).doesNotContain("\"startMs\"");
        assertThat(json).doesNotContain("\"endMs\"");
        assertThat(json).doesNotContain("\"isSessionEnd\"");
        assertThat(json).doesNotContain("\"sessionEnd\"");

        // 9필드 모두 포함
        assertThat(json).contains("\"ticker\"");
        assertThat(json).contains("\"sequence\"");
        assertThat(json).contains("\"text\"");
        assertThat(json).contains("\"speaker\"");
        assertThat(json).contains("\"timestamp\"");
    }

    @Test
    @DisplayName("publish — speaker 가 null 이면 JSON 에서 제외된다")
    void publish_speaker_null_제외() throws Exception {
        TranscriptSegment noSpeaker = new TranscriptSegment(
                "AAPL", "earnings-AAPL", 1, 0L, 1000L,
                "Welcome.", null, 1745000000L, false);

        publisher.publish(noSpeaker);

        ArgumentCaptor<TranscriptPublisher.Payload> cap = ArgumentCaptor.forClass(TranscriptPublisher.Payload.class);
        verify(messagingTemplate).convertAndSend(eq("/topic/transcript/AAPL"), cap.capture());

        String json = objectMapper.writeValueAsString(cap.getValue());
        assertThat(json).doesNotContain("\"speaker\"");
    }

    @Test
    @DisplayName("publish — is_session_end=true 도 정상 직렬화된다")
    void publish_세션_종료_플래그() throws Exception {
        TranscriptSegment endSeg = new TranscriptSegment(
                "MSFT", "earnings-MSFT", 99, 0L, 100L,
                "Thank you all.", "IR", 1745000000L, true);

        publisher.publish(endSeg);

        ArgumentCaptor<TranscriptPublisher.Payload> cap = ArgumentCaptor.forClass(TranscriptPublisher.Payload.class);
        verify(messagingTemplate).convertAndSend(eq("/topic/transcript/MSFT"), cap.capture());

        String json = objectMapper.writeValueAsString(cap.getValue());
        assertThat(json).contains("\"is_session_end\":true");
    }

    @Test
    @DisplayName("publish — messagingTemplate 예외 발생 시 흡수하고 재던지지 않는다")
    void publish_예외_흡수() {
        doThrow(new MessagingException("STOMP broker unreachable"))
                .when(messagingTemplate).convertAndSend(eq("/topic/transcript/NVDA"), any(Object.class));

        assertThatCode(() -> publisher.publish(SEGMENT)).doesNotThrowAnyException();

        verify(messagingTemplate).convertAndSend(eq("/topic/transcript/NVDA"), any(Object.class));
    }
}
