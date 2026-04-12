package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.presentation.trade.TradeCallbackRequest;
import com.earningwhisperer.presentation.trade.TradeResponse;
import jakarta.persistence.EntityNotFoundException;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.transaction.annotation.Transactional;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

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

    @Transactional(readOnly = true)
    public Page<TradeResponse> getMyTrades(Long userId, Pageable pageable) {
        return tradeRepository.findByUserId(userId, pageable)
                .map(TradeResponse::new);
    }

    /**
     * PENDING 상태의 Trade를 생성하고 tradeId + userId를 반환한다.
     * Trading Terminal이 tradeId를 받아 주문을 실행하고 콜백으로 결과를 보고한다.
     *
     * @param user   대상 사용자 (이미 조회된 엔티티)
     * @param ticker 종목 심볼
     * @param action RuleEngine 결과
     * @param mode   사용자의 TradingMode
     * @return PendingTradeResult (MANUAL이거나 HOLD이면 null)
     */
    @Transactional
    public PendingTradeResult createPendingTrade(User user, String ticker,
                                                  TradeAction action, TradingMode mode) {
        if (action == TradeAction.HOLD) {
            return null;
        }

        if (mode == TradingMode.MANUAL) {
            log.debug("[TradeService] MANUAL 모드 — 명령 생성 건너뜀 userId={}", user.getId());
            return null;
        }

        Trade trade = Trade.builder()
                .user(user)
                .signal(null)
                .ticker(ticker)
                .side(action)
                .orderType(OrderType.MARKET)
                .orderQty(PENDING_ORDER_QTY_SENTINEL)
                .price(0.0)
                .build();

        Trade saved = tradeRepository.save(trade);
        log.info("[TradeService] PENDING 거래 생성 - tradeId={} userId={} ticker={} action={} mode={}",
                saved.getId(), user.getId(), ticker, action, mode);
        return new PendingTradeResult(saved.getId(), user.getId());
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

        if ("EXECUTED".equals(request.getStatus())) {
            int qty = request.getExecutedQty() != null ? request.getExecutedQty() : 0;
            double price = request.getExecutedPrice() != null ? request.getExecutedPrice() : 0.0;
            trade.executed(qty, price, request.getBrokerOrderId());
            log.info("[TradeService] 체결 완료 - tradeId={} brokerOrderId={} qty={}",
                    tradeId, request.getBrokerOrderId(), qty);
        } else {
            trade.failed();
            log.warn("[TradeService] 체결 실패 - tradeId={} error={}", tradeId, request.getErrorMessage());
        }
        tradeRepository.save(trade);
    }
}
