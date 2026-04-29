package com.earningwhisperer.domain.market;

/**
 * 등락률(change_percent)을 기준으로 트렌드 라벨을 산출하는 유틸.
 *
 * 임계치 ±0.05% 는 매직넘버를 피하기 위한 상수.
 * - changePercent  >  +0.05  → "up"
 * - changePercent  <  -0.05  → "down"
 * - 그 외 (절대값 ≤ 0.05)    → "neutral"
 */
public final class MarketIndexTrend {

    public static final String UP = "up";
    public static final String DOWN = "down";
    public static final String NEUTRAL = "neutral";

    /** 트렌드 판정 임계치 (퍼센트). */
    static final double THRESHOLD = 0.05;

    private MarketIndexTrend() {
        // 유틸 클래스 — 인스턴스화 금지
    }

    public static String of(double changePercent) {
        if (changePercent > THRESHOLD) {
            return UP;
        }
        if (changePercent < -THRESHOLD) {
            return DOWN;
        }
        return NEUTRAL;
    }
}
