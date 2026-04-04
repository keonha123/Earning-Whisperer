package com.earningwhisperer.infrastructure.websocket;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
@DisplayName("LiveSignalPublisher 단위 테스트")
class LiveSignalPublisherTest {

    @Mock
    private SimpMessagingTemplate messagingTemplate;

    @InjectMocks
    private LiveSignalPublisher publisher;

    @Test
    @DisplayName("publish() 호출 시 /topic/live/{ticker} 목적지로 메시지가 전송된다")
    void publish_올바른_목적지로_메시지를_전송한다() {
        // Arrange
        LiveSignalMessage message = LiveSignalMessage.builder()
                .ticker("NVDA")
                .textChunk("Revenue exceeded expectations")
                .rawScore(0.85)
                .emaScore(0.78)
                .rationale("Strong earnings beat")
                .action("HOLD")
                .executedQty(0)
                .build();

        // Act
        publisher.publish(message);

        // Assert
        verify(messagingTemplate).convertAndSend("/topic/live/NVDA", message);
    }

    @Test
    @DisplayName("publish() 호출 시 메시지 객체가 그대로 전달된다")
    void publish_메시지_객체가_그대로_전달된다() {
        // Arrange
        LiveSignalMessage message = LiveSignalMessage.builder()
                .ticker("TSLA")
                .rawScore(-0.3)
                .emaScore(-0.25)
                .rationale("Guidance miss")
                .textChunk("We expect headwinds next quarter")
                .action("HOLD")
                .executedQty(0)
                .build();

        ArgumentCaptor<LiveSignalMessage> captor = ArgumentCaptor.forClass(LiveSignalMessage.class);

        // Act
        publisher.publish(message);

        // Assert
        verify(messagingTemplate).convertAndSend(
                org.mockito.ArgumentMatchers.eq("/topic/live/TSLA"),
                captor.capture()
        );
        assertThat(captor.getValue().getTicker()).isEqualTo("TSLA");
        assertThat(captor.getValue().getEmaScore()).isEqualTo(-0.25);
        assertThat(captor.getValue().getAction()).isEqualTo("HOLD");
    }
}
