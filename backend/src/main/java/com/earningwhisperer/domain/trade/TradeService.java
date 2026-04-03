package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
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
 *
 * 처리 흐름:
 * 1. HOLD → 즉시 null 반환 (명령 생성 없음)
 * 2. AUTO_PILOT 외 모드 → 즉시 null 반환
 * 3. Trade(PENDING) 생성 후 save() → tradeId 반환
 * 4. TradingSignalSubscriber가 tradeId를 Private WebSocket으로 라우팅
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TradeService {

    // TODO: 인증 구현 후 실제 userId로 교체
    private static final Long SYSTEM_USER_ID = 1L;
    // TODO: Phase 6에서 buyAmountRatio 기반 수량 계산으로 교체
    private static final int FIXED_ORDER_QTY = 1;

    private final TradeRepository tradeRepository;
    private final UserRepository userRepository;
    private final PortfolioSettingsService portfolioSettingsService;

    @Transactional(readOnly = true)
    public Page<TradeResponse> getMyTrades(Long userId, Pageable pageable) {
        return tradeRepository.findByUserId(userId, pageable)
                .map(TradeResponse::new);
    }

    /**
     * PENDING 상태의 Trade를 생성하고 tradeId + userId를 반환한다.
     * Trading Terminal이 tradeId를 받아 주문을 실행하고 콜백으로 결과를 보고한다.
     *
     * @return PendingTradeResult (AUTO_PILOT 아니거나 HOLD이면 null)
     */
    public PendingTradeResult createPendingTrade(String ticker, TradeAction action) {
        if (action == TradeAction.HOLD) {
            return null;
        }

        TradingMode mode = portfolioSettingsService.getSettings(SYSTEM_USER_ID).getTradingMode();
        if (mode != TradingMode.AUTO_PILOT) {
            log.debug("[TradeService] 자동매매 비활성화 모드({}) — 명령 생성 건너뜀", mode);
            return null;
        }

        User user = userRepository.findById(SYSTEM_USER_ID)
                .orElseThrow(() -> new IllegalStateException("시스템 사용자(id=1)가 존재하지 않습니다."));

        Trade trade = Trade.builder()
                .user(user)
                .signal(null)
                .ticker(ticker)
                .side(action)
                .orderType(OrderType.MARKET)
                .orderQty(FIXED_ORDER_QTY)
                .price(0.0)
                .build();

        Trade saved = tradeRepository.save(trade);
        log.info("[TradeService] PENDING 거래 생성 - tradeId={} ticker={} action={}", saved.getId(), ticker, action);
        return new PendingTradeResult(saved.getId(), SYSTEM_USER_ID);
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
            trade.executed(qty, request.getBrokerOrderId());
            log.info("[TradeService] 체결 완료 - tradeId={} brokerOrderId={} qty={}",
                    tradeId, request.getBrokerOrderId(), qty);
        } else {
            trade.failed();
            log.warn("[TradeService] 체결 실패 - tradeId={} error={}", tradeId, request.getErrorMessage());
        }
        tradeRepository.save(trade);
    }
}
