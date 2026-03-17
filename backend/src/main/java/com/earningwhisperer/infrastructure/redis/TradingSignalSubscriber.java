package com.earningwhisperer.infrastructure.redis;

import org.springframework.stereotype.Component;

/**
 * Redis trading-signals 채널 구독자.
 * Step 4에서 EmaService 연동 및 전체 로직을 구현한다.
 */
@Component
public class TradingSignalSubscriber {

    /**
     * Redis 채널에서 메시지를 수신하면 호출되는 진입점.
     * MessageListenerAdapter가 "handleMessage" 메서드명으로 위임.
     *
     * @param message 수신된 JSON 문자열
     */
    public void handleMessage(String message) {
        // Step 4에서 구현
    }
}
