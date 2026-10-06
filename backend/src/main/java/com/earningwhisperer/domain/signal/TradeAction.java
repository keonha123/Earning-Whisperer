package com.earningwhisperer.domain.signal;

/**
 * 주문 방향. 관망(HOLD)은 매매 신호 경로와 함께 #127 에서 제거했다 — 수동 주문 기록이
 * HOLD 를 받으면 SELF_PAPER 체결 반영에서 매도로 처리되는 구멍이 있었다.
 */
public enum TradeAction {
    BUY,
    SELL
}
