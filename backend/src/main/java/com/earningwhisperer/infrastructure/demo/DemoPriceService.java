package com.earningwhisperer.infrastructure.demo;

import com.earningwhisperer.infrastructure.websocket.DemoPriceMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Random;

/**
 * 데모룸 모의 주가 틱 서비스.
 *
 * NVDA Q3 FY2025 어닝콜(2024-11-20) 시점 주가 $145.50을 기준으로
 * 1초 간격으로 랜덤 워크를 생성하여 /topic/live/demo/price로 브로드캐스트한다.
 *
 * 어닝콜이 긍정적이었으므로 미세한 상승 바이어스(+0.02 bias)를 적용한다.
 * DemoReplayService와 독립적으로 동작한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DemoPriceService {

    private static final String TOPIC = "/topic/live/demo/price";
    private static final String TICKER = "NVDA";
    private static final double BASE_PRICE = 145.50;
    private static final double VOLATILITY = 0.18;  // 틱당 최대 변동폭 ($)
    private static final double UPWARD_BIAS = 0.02; // 상승 편향 ($)
    private static final double MAX_DRIFT = 12.0;   // 베이스 대비 최대 누적 변동 ($)
    private static final int PRICE_TICK_MS = 1_000;

    private final SimpMessagingTemplate messagingTemplate;
    private final Random random = new Random();

    private double currentPrice = BASE_PRICE;

    @EventListener(ApplicationReadyEvent.class)
    @Async
    public void startPriceFeed() {
        log.info("[DemoPrice] 주가 피드 시작 - ticker={} basePrice={}", TICKER, BASE_PRICE);

        while (!Thread.currentThread().isInterrupted()) {
            currentPrice = nextPrice(currentPrice);

            DemoPriceMessage message = DemoPriceMessage.builder()
                    .ticker(TICKER)
                    .price(round(currentPrice))
                    .change(round(currentPrice - BASE_PRICE))
                    .changePercent(round((currentPrice - BASE_PRICE) / BASE_PRICE * 100))
                    .timestamp(Instant.now().getEpochSecond())
                    .build();

            messagingTemplate.convertAndSend(TOPIC, message);

            try {
                Thread.sleep(PRICE_TICK_MS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                log.info("[DemoPrice] 인터럽트 수신. 주가 피드 종료.");
                return;
            }
        }
    }

    private double nextPrice(double price) {
        double delta = (random.nextDouble() * 2 - 1) * VOLATILITY + UPWARD_BIAS;
        double next = price + delta;

        // BASE_PRICE ± MAX_DRIFT 범위 초과 방지
        next = Math.max(BASE_PRICE - MAX_DRIFT, Math.min(BASE_PRICE + MAX_DRIFT, next));
        return next;
    }

    private double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }
}
