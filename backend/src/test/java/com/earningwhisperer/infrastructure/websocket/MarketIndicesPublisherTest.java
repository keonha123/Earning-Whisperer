package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.domain.market.MarketIndexSnapshot;
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
 * MarketIndicesPublisher 단위 테스트.
 *
 * 검증 포인트:
 *   1) /topic/market/indices 토픽으로 fan-out
 *   2) Contract 4.4 의 6필드(symbol/price/change_percent/trend/format/timestamp)만 페이로드에 포함
 *   3) JSON 직렬화 시 snake_case 보장 + 발행자 메타 누출 없음
 *   4) STOMP 전송 실패 예외 흡수 (재던지지 않음)
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("MarketIndicesPublisher 단위 테스트")
class MarketIndicesPublisherTest {

    @Mock
    private SimpMessagingTemplate messagingTemplate;

    @InjectMocks
    private MarketIndicesPublisher publisher;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private static final MarketIndexSnapshot SPX_SNAPSHOT = new MarketIndexSnapshot(
            "SPX", 5300.25, 0.85, "up", "index", 1745000000L);

    @Test
    @DisplayName("publish — 올바른 토픽(/topic/market/indices) 으로 전송된다")
    void publish_올바른_토픽으로_전송됨() {
        publisher.publish(SPX_SNAPSHOT);

        ArgumentCaptor<String> destinationCaptor = ArgumentCaptor.forClass(String.class);
        verify(messagingTemplate).convertAndSend(destinationCaptor.capture(), any(Object.class));

        assertThat(destinationCaptor.getValue()).isEqualTo("/topic/market/indices");
    }

    @Test
    @DisplayName("publish — 페이로드는 Contract 4.4 의 6필드만 보유 (메타 미포함)")
    void publish_페이로드_6필드만_보유() {
        publisher.publish(SPX_SNAPSHOT);

        ArgumentCaptor<MarketIndicesPublisher.Payload> payloadCaptor =
                ArgumentCaptor.forClass(MarketIndicesPublisher.Payload.class);
        verify(messagingTemplate).convertAndSend(eq("/topic/market/indices"), payloadCaptor.capture());

        MarketIndicesPublisher.Payload payload = payloadCaptor.getValue();
        assertThat(payload.getSymbol()).isEqualTo("SPX");
        assertThat(payload.getPrice()).isEqualTo(5300.25);
        assertThat(payload.getChangePercent()).isEqualTo(0.85);
        assertThat(payload.getTrend()).isEqualTo("up");
        assertThat(payload.getFormat()).isEqualTo("index");
        assertThat(payload.getTimestamp()).isEqualTo(1745000000L);
    }

    @Test
    @DisplayName("publish — JSON 직렬화 시 snake_case 보장 + 발행자 메타 누출 없음")
    void publish_JSON_직렬화_시_snake_case_보장() throws Exception {
        publisher.publish(SPX_SNAPSHOT);

        ArgumentCaptor<MarketIndicesPublisher.Payload> payloadCaptor =
                ArgumentCaptor.forClass(MarketIndicesPublisher.Payload.class);
        verify(messagingTemplate).convertAndSend(eq("/topic/market/indices"), payloadCaptor.capture());

        String json = objectMapper.writeValueAsString(payloadCaptor.getValue());

        // snake_case 보장
        assertThat(json).contains("\"change_percent\"");
        assertThat(json).doesNotContain("\"changePercent\"");

        // 6필드 모두 포함
        assertThat(json).contains("\"symbol\"");
        assertThat(json).contains("\"price\"");
        assertThat(json).contains("\"trend\"");
        assertThat(json).contains("\"format\"");
        assertThat(json).contains("\"timestamp\"");

        // 발행자 메타 누출 금지
        assertThat(json).doesNotContain("\"schema_version\"");
        assertThat(json).doesNotContain("\"schemaVersion\"");
        assertThat(json).doesNotContain("\"source\"");
        assertThat(json).doesNotContain("\"published_at\"");
        assertThat(json).doesNotContain("\"publishedAt\"");
    }

    @Test
    @DisplayName("publish — messagingTemplate 예외 발생 시 흡수하고 재던지지 않는다")
    void publish_messagingTemplate_예외_삼킨다() {
        doThrow(new MessagingException("STOMP broker unreachable"))
                .when(messagingTemplate).convertAndSend(eq("/topic/market/indices"), any(Object.class));

        // 정책: 캐시는 이미 갱신, 브로드캐스트는 best-effort. 예외 재던지지 않음.
        assertThatCode(() -> publisher.publish(SPX_SNAPSHOT))
                .doesNotThrowAnyException();

        // 호출 자체는 일어났는지 확인
        verify(messagingTemplate).convertAndSend(eq("/topic/market/indices"), any(Object.class));
    }
}
