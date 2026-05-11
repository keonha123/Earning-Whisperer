package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.market.MarketIndexFormat;
import com.earningwhisperer.domain.market.MarketIndexSnapshot;
import com.earningwhisperer.domain.market.MarketIndicesCache;
import com.earningwhisperer.infrastructure.websocket.MarketIndicesPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * Redis market-indices 채널 구독자.
 * api-spec.md Contract 6.3 의 단건 페이로드를 수신하여
 *   1) JSON 역직렬화
 *   2) 5종 심볼 검증 (지원 외 심볼은 WARN 로그 후 드롭)
 *   3) MarketIndicesCache.put → 최신 스냅샷 캐싱
 *   4) MarketIndicesPublisher.publish → STOMP /topic/market/indices fan-out
 * 순서로 처리한다.
 *
 * 파싱/필드 누락 등 예외는 모두 에러 로그만 남기고 삼킨다 (서버 중단 방지).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class MarketIndicesSubscriber {

    private final ObjectMapper objectMapper;
    private final MarketIndicesCache cache;
    private final MarketIndicesPublisher publisher;

    /**
     * Redis 채널에서 메시지 수신 시 호출되는 진입점.
     * MessageListenerAdapter가 "handleMessage" 메서드명으로 위임한다.
     */
    public void handleMessage(String message) {
        try {
            processMessage(message);
        } catch (Exception e) {
            log.error("[MarketIndices] 메시지 처리 중 예기치 않은 오류 - message={}", message, e);
        }
    }

    private void processMessage(String message) {
        MarketIndicesMessage payload;
        try {
            payload = objectMapper.readValue(message, MarketIndicesMessage.class);
        } catch (Exception e) {
            log.error("[MarketIndices] 메시지 파싱 실패 - message={}", message, e);
            return;
        }

        String symbol = payload.getSymbol();
        if (symbol == null || symbol.isBlank()) {
            log.error("[MarketIndices] symbol 누락 - message={}", message);
            return;
        }

        if (!MarketIndexFormat.isSupported(symbol)) {
            log.warn("[MarketIndices] 지원하지 않는 symbol 수신 - symbol={} (드롭)", symbol);
            return;
        }

        // Step 1: 캐시 갱신 → Step 2: STOMP fan-out
        MarketIndexSnapshot snapshot = cache.put(payload);
        publisher.publish(snapshot);
    }
}
