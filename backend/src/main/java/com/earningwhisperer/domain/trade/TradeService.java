package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import com.earningwhisperer.infrastructure.broker.BrokerApiClient;
import com.earningwhisperer.infrastructure.broker.BrokerApiException;
import com.earningwhisperer.infrastructure.broker.BrokerOrderRequest;
import com.earningwhisperer.infrastructure.broker.BrokerOrderResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * 매매 주문 실행 서비스.
 *
 * @Transactional 없음 — DB 커넥션이 외부 HTTP 구간에 물리지 않도록
 * tradeRepository.save()의 자체 트랜잭션만 활용한다.
 *
 * 처리 흐름:
 * 1. HOLD 또는 AUTO_PILOT 외 모드 → 즉시 0 반환 (주문 없음)
 * 2. Trade(PENDING) 생성 후 save() → 트랜잭션 완료, 커넥션 반환
 * 3. BrokerApiClient.placeOrder() 호출 (DB 커넥션 없는 상태)
 * 4. 성공: trade.executed() → save() / 실패: trade.failed() → save()
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
    private final BrokerApiClient brokerApiClient;

    /**
     * @return 체결 수량 (주문하지 않은 경우 0)
     */
    public int execute(String ticker, TradeAction action) {
        if (action == TradeAction.HOLD) {
            return 0;
        }

        TradingMode mode = portfolioSettingsService.getSettings(SYSTEM_USER_ID).getTradingMode();
        if (mode != TradingMode.AUTO_PILOT) {
            log.debug("[TradeService] 자동매매 비활성화 모드({}) — 주문 건너뜀", mode);
            return 0;
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

        trade = tradeRepository.save(trade); // Transaction 1 종료 → 커넥션 반환

        try {
            BrokerOrderRequest request = new BrokerOrderRequest(ticker, action, FIXED_ORDER_QTY);
            BrokerOrderResponse response = brokerApiClient.placeOrder(request); // DB 커넥션 없는 상태

            trade.executed(response.executedQty(), response.brokerOrderId());
            tradeRepository.save(trade); // Transaction 2 종료
            log.info("[TradeService] 주문 체결 - ticker={} action={} orderId={}",
                    ticker, action, response.brokerOrderId());
            return response.executedQty();

        } catch (BrokerApiException e) {
            trade.failed();
            tradeRepository.save(trade); // Transaction 3 종료
            log.error("[TradeService] 주문 실패 - ticker={} error={}", ticker, e.getMessage());
            return 0;
        }
    }
}
