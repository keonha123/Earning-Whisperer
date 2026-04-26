package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.user.User;

/**
 * 개별 사용자에 대한 시그널 처리 결과.
 * TradingSignalSubscriber가 팬아웃 후 사용자별 Trade 생성 및 WebSocket 라우팅에 사용한다.
 *
 * orderRatio: 사용자의 PortfolioSettings.buyAmountRatio.
 * BUY 시 "예수금 × ratio ÷ 현재가", SELL 시 "floor(보유수량 × ratio)"로 Trading Terminal이 수량을 산출한다.
 * 자본시장법상 수량 결정 주체는 사용자 로컬(터미널)이며, 서버는 비율까지만 결정한다.
 */
public record UserProcessedSignal(
        User user,
        TradeAction action,
        double aiScore,
        TradingMode mode,
        double orderRatio
) {}
