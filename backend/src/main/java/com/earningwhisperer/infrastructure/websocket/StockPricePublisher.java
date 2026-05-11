package com.earningwhisperer.infrastructure.websocket;

import com.earningwhisperer.domain.stock.StockPriceSnapshot;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class StockPricePublisher {

    private static final String TOPIC = "/topic/prices";

    private final SimpMessagingTemplate messagingTemplate;
    private final StockPriceCache priceCache;

    @Scheduled(fixedRate = 1000)
    public void flush() {
        List<StockPriceSnapshot> dirty = priceCache.getDirtyAndClear();
        if (dirty.isEmpty()) return;
        try {
            messagingTemplate.convertAndSend(TOPIC, dirty);
        } catch (Exception e) {
            log.warn("[StockPricePublisher] STOMP 발행 실패 — 다음 사이클에 재시도");
        }
    }
}
