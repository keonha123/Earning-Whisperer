package com.earningwhisperer.infrastructure.redis;

import com.earningwhisperer.domain.signal.SignalService;
import com.earningwhisperer.domain.signal.UserProcessedSignal;
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

import java.util.List;

/**
 * Redis trading-signals 채널 구독자 — Facade(오케스트레이터) 역할.
 *
 * @Transactional 없음. 각 서비스의 트랜잭션이 독립적으로 커밋된 후 다음 단계를 실행한다.
 *
 * 처리 흐름:
 * 1. JSON → TradingSignalMessage 역직렬화
 * 2. SignalService.processSignalForAllUsers() — 글로벌 EMA + 전체 사용자 룰 평가 + SignalHistory 저장
 * 3. 사용자별 TradeService.createPendingTrade() — PENDING Trade 생성 (SEMI_AUTO/AUTO_PILOT)
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
        try {
            processMessage(message);
        } catch (Exception e) {
            log.error("[TradingSignal] 메시지 처리 중 예기치 않은 오류 - message={}", message, e);
        }
    }

    private void processMessage(String message) {
        TradingSignalMessage signal;
        try {
            signal = objectMapper.readValue(message, TradingSignalMessage.class);
        } catch (Exception e) {
            log.error("[TradingSignal] 메시지 파싱 실패 - message={}", message, e);
            return;
        }

        // Step 1: 글로벌 EMA 계산 + 전체 사용자 RuleEngine 평가 + SignalHistory batch 저장
        List<UserProcessedSignal> userResults = signalService.processSignalForAllUsers(signal);

        // Step 2: 사용자별 Trade 생성 + Private WebSocket 라우팅
        for (UserProcessedSignal result : userResults) {
            try {
                PendingTradeResult tradeResult = tradeService.createPendingTrade(
                        result.user(), signal.getTicker(), result.action(), result.mode());

                if (tradeResult != null) {
                    TradeCommandMessage command = TradeCommandMessage.builder()
                            .tradeId(tradeResult.tradeId())
                            .action(result.action().name())
                            .targetQty(1) // TODO: buyAmountRatio 기반 동적 수량 계산 (Phase 후속)
                            .ticker(signal.getTicker())
                            .emaScore(result.emaScore())
                            .build();
                    tradeCommandPublisher.publish(tradeResult.userId(), command);
                }
            } catch (Exception e) {
                Long userId = result.user() != null ? result.user().getId() : null;
                log.error("[TradingSignal] 사용자별 Trade 처리 실패 - userId={} ticker={}",
                        userId, signal.getTicker(), e);
            }
        }

        // Step 3: WebSocket 브로드캐스트 (Frontend 데모용 Public 채널)
        // 공개 채널의 action은 EMA 부호 기반 방향성 표시 (개인화 판단 아님)
        double emaScore = userResults.isEmpty() ? 0.0 : userResults.get(0).emaScore();
        String publicAction = emaScore >= 0.6 ? "BUY" : emaScore <= -0.6 ? "SELL" : "HOLD";
        LiveSignalMessage liveMessage = LiveSignalMessage.builder()
                .ticker(signal.getTicker())
                .textChunk(signal.getTextChunk())
                .rawScore(signal.getRawScore())
                .emaScore(emaScore)
                .rationale(signal.getRationale())
                .action(publicAction)
                .executedQty(0)
                .build();

        liveSignalPublisher.publish(liveMessage);
    }
}
