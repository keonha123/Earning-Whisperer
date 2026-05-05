package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.infrastructure.websocket.TradeCommandMessage;
import com.earningwhisperer.presentation.trade.TradeCallbackRequest;
import com.earningwhisperer.presentation.trade.TradeResponse;
import jakarta.persistence.EntityNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 매매 명령 생성 서비스.
 *
 * 백엔드는 KIS 증권사 API를 직접 호출하지 않는다.
 * 역할: PENDING Trade 생성 → Trading Terminal로 매매 명령 라우팅
 * 실제 주문 실행은 Trading Terminal(데스크톱 앱)이 담당하며,
 * 체결 결과는 콜백 API(POST /api/v1/trades/{tradeId}/callback)로 수신한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TradeService {

    /**
     * PENDING 시점 orderQty 센티널. 실제 수량은 Trading Terminal이 산출해
     * 체결 콜백으로 보고하며, Trade.executed()가 executedQty로 덮어쓴다.
     */
    private static final int PENDING_ORDER_QTY_SENTINEL = 0;

    private final TradeRepository tradeRepository;

    @Value("${app.trade.pending-ttl-seconds:30}")
    private long pendingTtlSeconds;

    @Transactional(readOnly = true)
    public Page<TradeResponse> getMyTrades(Long userId, Pageable pageable) {
        return tradeRepository.findByUserId(userId, pageable)
                .map(TradeResponse::new);
    }

    /**
     * PENDING 상태의 Trade를 생성하고 tradeId + userId를 반환한다.
     * Trading Terminal이 tradeId를 받아 주문을 실행하고 콜백으로 결과를 보고한다.
     *
     * @param user             대상 사용자 (이미 조회된 엔티티)
     * @param brokerAccountId  거래 대상 BrokerAccount (활성 broker)
     * @param ticker           종목 심볼
     * @param action           RuleEngine 결과
     * @param mode             사용자의 TradingMode
     * @param orderRatio       주문 비율 — 재접속 시 명령 복원용으로 엔티티에 보존
     * @param aiScore          시그널 AI 점수 — 재접속 시 명령 복원용
     * @return PendingTradeResult (MANUAL이거나 HOLD이면 null)
     */
    @Transactional
    public PendingTradeResult createPendingTrade(User user, Long brokerAccountId, String ticker,
                                                  TradeAction action, TradingMode mode,
                                                  double orderRatio, double aiScore) {
        if (action == TradeAction.HOLD) {
            return null;
        }

        if (mode == TradingMode.MANUAL) {
            log.debug("[TradeService] MANUAL 모드 — 명령 생성 건너뜀 userId={}", user.getId());
            return null;
        }

        Trade trade = Trade.builder()
                .user(user)
                .brokerAccountId(brokerAccountId)
                .signal(null)
                .ticker(ticker)
                .side(action)
                .orderType(OrderType.MARKET)
                .orderQty(PENDING_ORDER_QTY_SENTINEL)
                .price(0.0)
                .orderRatio(orderRatio)
                .aiScore(aiScore)
                .build();

        Trade saved = tradeRepository.save(trade);
        log.info("[TradeService] PENDING 거래 생성 - tradeId={} userId={} brokerAccountId={} ticker={} action={} mode={}",
                saved.getId(), user.getId(), brokerAccountId, ticker, action, mode);
        return new PendingTradeResult(saved.getId(), user.getId());
    }

    /**
     * Terminal 재접속 시 호출. 활성 BrokerAccount 의 TTL 내 미만료 PENDING 명령을 복원한다.
     * orderRatio/aiScore 가 null 인 레거시 행은 제외한다 (복원 불가능 — 폐기).
     */
    @Transactional(readOnly = true)
    public List<TradeCommandMessage> getPendingCommandsForUser(Long userId, Long brokerAccountId) {
        LocalDateTime threshold = LocalDateTime.now().minusSeconds(pendingTtlSeconds);
        return tradeRepository
                .findByBrokerAccountIdAndStatusAndCreatedAtAfter(brokerAccountId, TradeStatus.PENDING, threshold)
                .stream()
                .filter(t -> t.getUser().getId().equals(userId)) // 소유권 방어 (이중 가드)
                .filter(t -> t.getOrderRatio() != null && t.getAiScore() != null)
                .map(t -> TradeCommandMessage.builder()
                        .tradeId(t.getId())
                        .brokerAccountId(t.getBrokerAccountId())
                        .action(t.getSide().name())
                        .orderRatio(t.getOrderRatio())
                        .ticker(t.getTicker())
                        .aiScore(t.getAiScore())
                        .build())
                .toList();
    }

    /**
     * Scheduler 진입점. TTL 초과한 PENDING Trade 를 EXPIRED 로 일괄 전환한다.
     *
     * 단일 @Modifying UPDATE 로 처리하므로 (1) 멀티 인스턴스 동시 실행 시 lost update 가 없고
     * (2) WHERE status = 'PENDING' 절이 동시에 commit 된 EXECUTED 콜백을 절대 덮어쓰지 않는다.
     *
     * @return 만료된 Trade 개수
     */
    @Transactional
    public int expireStalePending() {
        LocalDateTime threshold = LocalDateTime.now().minusSeconds(pendingTtlSeconds);
        int affected = tradeRepository.expirePendingBefore(threshold);
        if (affected > 0) {
            log.info("[TradeService] PENDING TTL 만료 전환 - count={} threshold={}",
                    affected, threshold);
        }
        return affected;
    }

    /**
     * Contract 4 — Trading Terminal 체결 콜백 처리.
     * Trade 상태를 PENDING → EXECUTED / FAILED 로 전환한다.
     * 순수 DB 작업이므로 @Transactional 사용 (외부 HTTP 없음).
     *
     * @param callerId JWT에서 추출한 요청자 userId — 소유권 검증에 사용
     */
    @Transactional
    public void processCallback(Long tradeId, Long callerId, TradeCallbackRequest request) {
        Trade trade = tradeRepository.findById(tradeId)
                .orElseThrow(() -> new EntityNotFoundException("Trade를 찾을 수 없습니다. tradeId=" + tradeId));

        if (!trade.getUser().getId().equals(callerId)) {
            throw new SecurityException("Trade 소유권 불일치 - tradeId=" + tradeId + " callerId=" + callerId);
        }

        TradeStatus before = trade.getStatus();
        if ("EXECUTED".equals(request.getStatus())) {
            int qty = request.getExecutedQty() != null ? request.getExecutedQty() : 0;
            double price = request.getExecutedPrice() != null ? request.getExecutedPrice() : 0.0;
            trade.executed(qty, price, request.getBrokerOrderId());
            if (before == TradeStatus.EXECUTED) {
                log.warn("[TradeService] 멱등 콜백 감지(EXECUTED 재수신) - tradeId={} brokerOrderId={}",
                        tradeId, request.getBrokerOrderId());
            } else {
                log.info("[TradeService] 체결 완료 - tradeId={} brokerOrderId={} qty={}",
                        tradeId, request.getBrokerOrderId(), qty);
            }
        } else {
            trade.failed();
            if (before == TradeStatus.FAILED) {
                log.warn("[TradeService] 멱등 콜백 감지(FAILED 재수신) - tradeId={}", tradeId);
            } else {
                log.warn("[TradeService] 체결 실패 - tradeId={} error={}", tradeId, request.getErrorMessage());
            }
        }
        tradeRepository.save(trade);
    }
}
