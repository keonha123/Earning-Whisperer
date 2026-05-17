package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.market.MarketIndexSnapshot;
import com.earningwhisperer.domain.market.MarketIndicesCache;
import com.earningwhisperer.infrastructure.websocket.MarketIndicesPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * MarketIndicesSubscriber 단위 테스트.
 * - 정상 페이로드 → cache.put → publisher.publish 순서 검증
 * - 알 수 없는 symbol 드롭
 * - JSON 파싱 실패 시 후속 호출 없음
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("MarketIndicesSubscriber 단위 테스트")
class MarketIndicesSubscriberTest {

    @Mock private MarketIndicesCache cache;
    @Mock private MarketIndicesPublisher publisher;
    @Spy  private ObjectMapper objectMapper;

    @InjectMocks
    private MarketIndicesSubscriber subscriber;

    private static final String SPX_MESSAGE = """
            {
              "schema_version": "1.0",
              "source": "data-pipeline",
              "symbol": "SPX",
              "price": 5300.25,
              "change_percent": 0.85,
              "timestamp": 1745000000,
              "published_at": 1745000005
            }
            """;

    @Test
    @DisplayName("정상 메시지 수신 시 cache.put 후 publisher.publish 호출된다")
    void 정상_메시지_처리_순서_검증() {
        // Arrange — cache.put 이 반환할 스냅샷 stub
        MarketIndexSnapshot stubSnapshot = new MarketIndexSnapshot(
                "SPX", 5300.25, 0.85, "up", "index", 1745000000L);
        when(cache.put(any(MarketIndicesMessage.class))).thenReturn(stubSnapshot);

        // Act
        subscriber.handleMessage(SPX_MESSAGE);

        // Assert — 호출 순서 검증
        InOrder inOrder = inOrder(cache, publisher);
        ArgumentCaptor<MarketIndicesMessage> messageCaptor = ArgumentCaptor.forClass(MarketIndicesMessage.class);
        inOrder.verify(cache).put(messageCaptor.capture());
        inOrder.verify(publisher).publish(stubSnapshot);

        // 페이로드 필드 검증 (snake_case 매핑 정상 동작)
        MarketIndicesMessage parsed = messageCaptor.getValue();
        assertThat(parsed.getSymbol()).isEqualTo("SPX");
        assertThat(parsed.getPrice()).isEqualTo(5300.25);
        assertThat(parsed.getChangePercent()).isEqualTo(0.85);
        assertThat(parsed.getTimestamp()).isEqualTo(1745000000L);
        assertThat(parsed.getPublishedAt()).isEqualTo(1745000005L);
    }

    @Test
    @DisplayName("published_at 누락 시에도 정상 처리된다 (옵셔널 필드)")
    void published_at_누락_정상_처리() {
        String message = """
                {
                  "schema_version": "1.0",
                  "source": "data-pipeline",
                  "symbol": "10Y",
                  "price": 4.35,
                  "change_percent": -0.10,
                  "timestamp": 1745000100
                }
                """;
        when(cache.put(any())).thenReturn(new MarketIndexSnapshot(
                "10Y", 4.35, -0.10, "down", "percent", 1745000100L));

        subscriber.handleMessage(message);

        verify(cache).put(any());
        verify(publisher).publish(any());
    }

    @Test
    @DisplayName("지원하지 않는 symbol 수신 시 cache/publisher 호출되지 않는다")
    void 미지원_symbol_드롭() {
        String message = """
                {
                  "symbol": "AAPL",
                  "price": 195.0,
                  "change_percent": 0.5,
                  "timestamp": 1745000000
                }
                """;

        subscriber.handleMessage(message);

        verify(cache, never()).put(any());
        verify(publisher, never()).publish(any());
    }

    @Test
    @DisplayName("symbol 누락 메시지는 드롭된다")
    void symbol_누락_드롭() {
        String message = """
                {
                  "price": 100.0,
                  "change_percent": 0.0,
                  "timestamp": 1745000000
                }
                """;

        subscriber.handleMessage(message);

        verify(cache, never()).put(any());
        verify(publisher, never()).publish(any());
    }

    @Test
    @DisplayName("JSON 파싱 실패 시 cache/publisher 모두 호출되지 않는다")
    void JSON_파싱_실패시_후속_호출_없음() {
        subscriber.handleMessage("{ invalid json }");

        verify(cache, never()).put(any());
        verify(publisher, never()).publish(any());
    }

    @Test
    @DisplayName("빈 문자열 수신 시에도 예외 전파 없이 드롭된다")
    void 빈_문자열_드롭() {
        subscriber.handleMessage("");

        verify(cache, never()).put(any());
        verify(publisher, never()).publish(any());
    }

    @Test
    @DisplayName("publisher.publish 예외를 삼키고 후속 메시지를 정상 처리한다")
    void publisher_publish_예외_삼킨다_후속_메시지_정상_처리() {
        // Arrange — 첫 메시지 처리 시 publisher 가 예외를 던짐
        MarketIndexSnapshot stubSnapshot = new MarketIndexSnapshot(
                "SPX", 5300.25, 0.85, "up", "index", 1745000000L);
        when(cache.put(any(MarketIndicesMessage.class))).thenReturn(stubSnapshot);
        doThrow(new RuntimeException("STOMP fail"))
                .when(publisher).publish(any(MarketIndexSnapshot.class));

        // Act + Assert — 예외가 외부로 전파되지 않음 (handleMessage 가 흡수)
        assertThatCode(() -> subscriber.handleMessage(SPX_MESSAGE))
                .doesNotThrowAnyException();

        // 첫 메시지에서도 cache 갱신 / publish 호출은 시도됨
        verify(cache).put(any(MarketIndicesMessage.class));
        verify(publisher).publish(any(MarketIndexSnapshot.class));

        // Arrange — 두 번째 메시지 정상 처리 (mock 상태 초기화)
        reset(publisher, cache);
        MarketIndexSnapshot secondSnapshot = new MarketIndexSnapshot(
                "NDX", 18500.50, 0.15, "up", "index", 1745000100L);
        when(cache.put(any(MarketIndicesMessage.class))).thenReturn(secondSnapshot);
        doNothing().when(publisher).publish(any(MarketIndexSnapshot.class));

        String secondMessage = """
                {
                  "schema_version": "1.0",
                  "source": "data-pipeline",
                  "symbol": "NDX",
                  "price": 18500.50,
                  "change_percent": 0.15,
                  "timestamp": 1745000100
                }
                """;

        // Act
        assertThatCode(() -> subscriber.handleMessage(secondMessage))
                .doesNotThrowAnyException();

        // Assert — 두 번째 메시지는 정상 cache.put + publisher.publish 흐름
        verify(cache).put(any(MarketIndicesMessage.class));
        verify(publisher).publish(any(MarketIndexSnapshot.class));
    }
}
