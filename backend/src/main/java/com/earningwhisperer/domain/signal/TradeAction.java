package com.earningwhisperer.domain.signal;

public enum TradeAction {
    BUY,   // 매수 시그널
    SELL,  // 매도 시그널
    HOLD   // 관망 (임계치 미달 또는 방어 로직 작동)
}
