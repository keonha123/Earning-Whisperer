package com.earningwhisperer.domain.trade;

public enum TradeStatus {
    PENDING,   // 증권사 API에 주문 전송 완료, 체결 대기 중
    EXECUTED,  // 체결 완료
    FAILED     // 주문 실패 (API 오류, 잔고 부족 등)
}
