package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.ProcessedSignal;
import com.earningwhisperer.domain.signal.SignalService;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.trade.PendingTradeResult;
import com.earningwhisperer.domain.trade.TradeService;
import com.earningwhisperer.infrastructure.websocket.LiveSignalMessage;
import com.earningwhisperer.infrastructure.websocket.LiveSignalPublisher;
import com.earningwhisperer.infrastructure.websocket.TradeCommandMessage;
import com.earningwhisperer.infrastructure.websocket.TradeCommandPublisher;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * Redis trading-signals 채널 구독자 — Facade(오케스트레이터) 역할.
 *
 * @Transactional 없음. 각 서비스의 트랜잭션이 독립적으로 커밋된 후 다음 단계를 실행한다.
 *
 * 처리 흐름:
 * 1. JSON → TradingSignalMessage 역직렬화
 * 2. SignalService.processSignal() — EMA + 룰 엔진 + SignalHistory 저장 [트랜잭션 종료]
 * 3. TradeService.createPendingTrade() — PENDING Trade 생성 [트랜잭션 종료]
 *    (실제 주문 실행은 Trading Terminal이 담당. 체결 결과는 콜백 API로 수신)
 * 4. LiveSignalPublisher.publish() — WebSocket 브로드캐스트 (Frontend 데모용)
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
    private final TradeCommandPublisher tradeCommandPublisher;

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

        // Step 3: PENDING Trade 생성 → Private WebSocket으로 Trading Terminal에 매매 명령 전송
        PendingTradeResult tradeResult = tradeService.createPendingTrade(signal.getTicker(), processed.action());
        if (tradeResult != null) {
            TradeCommandMessage command = TradeCommandMessage.builder()
                    .tradeId(tradeResult.tradeId())
                    .action(processed.action().name())
                    .targetQty(1) // TODO: buyAmountRatio 기반 동적 수량 계산 (Phase 후속)
                    .ticker(signal.getTicker())
                    .emaScore(processed.emaScore())
                    .build();
            tradeCommandPublisher.publish(tradeResult.userId(), command);
        }

        // Step 4: WebSocket 브로드캐스트 (Frontend 데모용 Public 채널)
        // executedQty는 Trading Terminal 콜백 수신 후 확정되므로 여기서는 0
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
