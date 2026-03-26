package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.ProcessedSignal;
import com.earningwhisperer.domain.signal.SignalService;
import com.earningwhisperer.domain.trade.TradeService;
import com.earningwhisperer.infrastructure.websocket.LiveSignalMessage;
import com.earningwhisperer.infrastructure.websocket.LiveSignalPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * Redis trading-signals 채널 구독자 — Facade(오케스트레이터) 역할.
 *
 * @Transactional 없음. 각 서비스의 트랜잭션이 독립적으로 커밋된 후 다음 단계를 실행한다.
 * → DB 커넥션이 외부 HTTP 구간(KIS API)에 물리지 않도록 보장.
 *
 * 처리 흐름:
 * 1. JSON → TradingSignalMessage 역직렬화
 * 2. SignalService.processSignal() — EMA + 룰 엔진 + SignalHistory 저장 [트랜잭션 종료]
 * 3. TradeService.execute() — 주문 실행 + Trade 저장 [독립 트랜잭션, KIS HTTP 포함]
 * 4. LiveSignalPublisher.publish() — WebSocket 브로드캐스트 (executedQty 반영)
 *
 * 파싱 실패 시: 에러 로그만 출력하고 예외를 삼킨다 (서버 중단 방지).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TradingSignalSubscriber {

    private final SignalService signalService;
    private final TradeService tradeService;
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

        // Step 2: DB 전용 트랜잭션 — 완료 후 커넥션 즉시 반환
        ProcessedSignal processed = signalService.processSignal(signal);

        // Step 3: 독립 주문 실행 — KIS HTTP 호출은 DB 커넥션 없는 상태
        int executedQty = tradeService.execute(signal.getTicker(), processed.action());

        // Step 4: WebSocket 브로드캐스트
        LiveSignalMessage liveMessage = LiveSignalMessage.builder()
                .ticker(signal.getTicker())
                .textChunk(signal.getTextChunk())
                .rawScore(signal.getRawScore())
                .emaScore(processed.emaScore())
                .rationale(signal.getRationale())
                .action(processed.action().name())
                .executedQty(executedQty)
                .build();

        liveSignalPublisher.publish(liveMessage);
    }
}
