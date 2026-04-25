package com.earningwhisperer.infrastructure.demo;

import com.earningwhisperer.infrastructure.websocket.DemoSignalMessage;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * DemoReplayService 단위 테스트.
 *
 * 무한 루프 자체는 테스트하지 않으며,
 * 메시지 빌드 로직과 is_session_end 플래그 설정을 검증한다.
 */
@ExtendWith(MockitoExtension.class)
class DemoReplayServiceTest {

    @Mock private SimpMessagingTemplate messagingTemplate;

    private DemoReplayService service;

    @BeforeEach
    void setUp() {
        service = new DemoReplayService(messagingTemplate, new ObjectMapper());
    }

    @Test
    void buildMessage_일반_이벤트_isSessionEnd가_false() {
        DemoReplayEvent event = new DemoReplayEvent(
                "NVDA", "Revenue grew 94% year-over-year.",
                0.60, "강한 매수 신호.", "BUY", 1732143670L);

        DemoSignalMessage msg = service.buildMessage(event, false);

        assertThat(msg.getTicker()).isEqualTo("NVDA");
        assertThat(msg.getAiScore()).isEqualTo(0.60);
        assertThat(msg.getAction()).isEqualTo("BUY");
        assertThat(msg.isSessionEnd()).isFalse();
    }

    @Test
    void buildMessage_세션_종료_이벤트_isSessionEnd가_true() {
        DemoReplayEvent event = new DemoReplayEvent(
                "NVDA", "In summary, NVIDIA delivered record results.",
                0.68, "사상 최고 실적 마무리.", "BUY", 1732143750L);

        DemoSignalMessage msg = service.buildMessage(event, true);

        assertThat(msg.isSessionEnd()).isTrue();
        assertThat(msg.getTicker()).isEqualTo("NVDA");
    }

    @Test
    void buildMessage_필드_매핑_정확성() {
        DemoReplayEvent event = new DemoReplayEvent(
                "NVDA", "test text", 0.49,
                "중국 규제 리스크.", "HOLD", 1732143690L);

        DemoSignalMessage msg = service.buildMessage(event, false);

        assertThat(msg.getTextChunk()).isEqualTo("test text");
        assertThat(msg.getAiScore()).isEqualTo(0.49);
        assertThat(msg.getRationale()).isEqualTo("중국 규제 리스크.");
        assertThat(msg.getAction()).isEqualTo("HOLD");
        assertThat(msg.getTimestamp()).isEqualTo(1732143690L);
    }
}
