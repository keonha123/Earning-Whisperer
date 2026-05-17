package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.domain.market.MarketIndexSnapshot;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

/**
 * 5종 시장 지수의 실시간 스트림을 STOMP 토픽으로 fan-out 한다.
 *
 * Contract 4.4 규격:
 *   Topic   : /topic/market/indices
 *   Payload : symbol, price, change_percent, trend, format, timestamp
 *
 * 발행자 메타(schema_version, source, published_at)는 클라이언트로 전달하지 않는다.
 *
 * 정책: 캐시는 항상 갱신, 브로드캐스트는 best-effort.
 *       STOMP fan-out 실패 시 다음 사이클(60초 후) 새 데이터로 자연 복구된다.
 *       따라서 publish() 는 예외를 흡수하고 재던지지 않는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MarketIndicesPublisher {

    static final String TOPIC = "/topic/market/indices";

    private final SimpMessagingTemplate messagingTemplate;

    public void publish(MarketIndexSnapshot snapshot) {
        Payload payload = Payload.from(snapshot);
        try {
            messagingTemplate.convertAndSend(TOPIC, payload);
            log.debug("[WebSocket] 시장지수 브로드캐스트 - symbol={} price={} trend={}",
                    payload.getSymbol(), payload.getPrice(), payload.getTrend());
        } catch (Exception e) {
            // 캐시는 이미 Subscriber 단계에서 갱신 완료. 1분 후 재시도가 정책이므로 재던지지 않는다.
            log.error("STOMP fan-out 실패 — 캐시는 갱신됨, 다음 사이클 갱신 대기. symbol={}, error={}",
                    payload.getSymbol(), e.getMessage(), e);
        }
    }

    /**
     * STOMP 직렬화 전용 페이로드.
     * Contract 4.4 의 6필드를 snake_case 로 직렬화한다.
     */
    @Getter
    @Builder
    public static class Payload {
        private final String symbol;
        private final double price;

        @JsonProperty("change_percent")
        private final double changePercent;

        private final String trend;
        private final String format;
        private final long timestamp;

        static Payload from(MarketIndexSnapshot snapshot) {
            return Payload.builder()
                    .symbol(snapshot.symbol())
                    .price(snapshot.price())
                    .changePercent(snapshot.changePercent())
                    .trend(snapshot.trend())
                    .format(snapshot.format())
                    .timestamp(snapshot.timestamp())
                    .build();
        }
    }
}
