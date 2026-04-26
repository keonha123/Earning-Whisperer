package com.earningwhisperer.domain.signal;

import com.earningwhisperer.domain.portfolio.TradingMode;
import com.earningwhisperer.domain.user.User;

/**
 * 개별 사용자에 대한 시그널 처리 결과.
 * TradingSignalSubscriber가 팬아웃 후 사용자별 Trade 생성 및 WebSocket 라우팅에 사용한다.
 */
public record UserProcessedSignal(
        User user,
        TradeAction action,
        double aiScore,
        TradingMode mode
) {}
