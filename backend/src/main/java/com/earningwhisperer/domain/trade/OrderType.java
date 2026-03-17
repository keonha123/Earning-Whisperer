package com.earningwhisperer.domain.trade;

public enum OrderType {
    MARKET, // 시장가 주문 (즉시 체결, 가격 지정 불필요)
    LIMIT   // 지정가 주문 (특정 가격 이하/이상에서만 체결)
}
