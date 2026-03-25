package com.earningwhisperer.domain.signal;

/**
 * SignalService.processSignal()의 반환 값 객체.
 * EMA 계산 결과와 룰 엔진의 최종 매매 결정을 함께 전달한다.
 */
public record ProcessedSignal(double emaScore, TradeAction action) {}
