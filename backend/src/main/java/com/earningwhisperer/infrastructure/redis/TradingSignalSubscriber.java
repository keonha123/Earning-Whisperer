package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.EmaService;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * Redis trading-signals 채널 구독자.
 *
 * 처리 흐름:
 * 1. JSON 메시지 → TradingSignalMessage 역직렬화
 * 2. EmaService.process()로 EMA 계산
 * 3. 결과 로그 출력
 *
 * 파싱 실패 시: 에러 로그만 출력하고 예외를 삼킨다 (서버 중단 방지).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TradingSignalSubscriber {

    private final EmaService emaService;
    private final ObjectMapper objectMapper;

    /**
     * Redis 채널에서 메시지를 수신하면 호출되는 진입점.
     * MessageListenerAdapter가 "handleMessage" 메서드명으로 위임.
     *
     * @param message 수신된 JSON 문자열
     */
    public void handleMessage(String message) {
        TradingSignalMessage signal;
        try {
            signal = objectMapper.readValue(message, TradingSignalMessage.class);
        } catch (Exception e) {
            log.error("[TradingSignal] 메시지 파싱 실패 - message={}, error={}", message, e.getMessage());
            return;
        }

        double emaScore = emaService.process(signal.getTicker(), signal.getRawScore());

        log.info("[TradingSignal] ticker={} rawScore={} emaScore={}",
                signal.getTicker(), signal.getRawScore(), emaScore);
    }
}
