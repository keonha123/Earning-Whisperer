package com.earningwhisperer.domain.trade;

import com.earningwhisperer.domain.portfolio.PortfolioSettingsService;
import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.signal.TradeAction;
import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import lombok.RequiredArgsConstructor;
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

    /**
     * PENDING 상태의 Trade를 생성하고 tradeId를 반환한다.
     * Trading Terminal이 이 tradeId를 받아 주문을 실행하고 콜백으로 결과를 보고한다.
     *
     * @return 생성된 Trade ID (주문 생성하지 않은 경우 null)
     */
    public Long createPendingTrade(String ticker, TradeAction action) {
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
        return saved.getId();
    }
}
