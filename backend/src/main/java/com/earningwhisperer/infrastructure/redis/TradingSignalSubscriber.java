package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.ProcessedSignal;
import com.earningwhisperer.domain.signal.SignalService;
import com.earningwhisperer.infrastructure.websocket.LiveSignalMessage;
import com.earningwhisperer.infrastructure.websocket.LiveSignalPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * Redis trading-signals 채널 구독자.
 *
 * 처리 흐름:
 * 1. JSON 메시지 → TradingSignalMessage 역직렬화
 * 2. SignalService.processSignal() — EMA 계산 + 룰 엔진 판단 + SignalHistory 저장
 * 3. LiveSignalPublisher로 WebSocket 브로드캐스트
 *
 * 파싱 실패 시: 에러 로그만 출력하고 예외를 삼킨다 (서버 중단 방지).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TradingSignalSubscriber {

    private final SignalService signalService;
    private final ObjectMapper objectMapper;
    private final LiveSignalPublisher liveSignalPublisher;

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

        ProcessedSignal processed = signalService.processSignal(signal);

        LiveSignalMessage liveMessage = LiveSignalMessage.builder()
                .ticker(signal.getTicker())
                .textChunk(signal.getTextChunk())
                .rawScore(signal.getRawScore())
                .emaScore(processed.emaScore())
                .rationale(signal.getRationale())
                .action(processed.action().name())
                .executedQty(0)
                .build();

        liveSignalPublisher.publish(liveMessage);
    }
}
