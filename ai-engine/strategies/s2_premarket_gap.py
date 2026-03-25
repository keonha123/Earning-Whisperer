# strategies/s2_premarket_gap.py — 전략 2: Pre-Market 갭 트레이딩
# 논문: Berkman et al.(2009), Bhattacharya et al.(2007)
# 승률: 54~60%

def evaluate_premarket_gap(gap_pct, raw_score, rsi_14, premarket_volume_ratio, prev_close):
    if gap_pct is None:
        return {"approved": False, "reason": "gap_pct 없음"}
    abs_gap   = abs(gap_pct)
    direction = "LONG" if gap_pct > 0 else "SHORT"

    if abs_gap < 1.0:
        return {"approved": False, "reason": f"갭 {gap_pct:.1f}% 너무 작음"}

    # Gap Fill: 갭 5%+ + RSI 과매수 → 역추세
    if abs_gap > 5.0 and rsi_14 and rsi_14 > 72:
        fill_target = (prev_close or 0) + (gap_pct / 100 * (prev_close or 0)) * 0.50
        return {
            "approved": True, "strategy": "GAP_FILL",
            "direction": "SHORT" if direction == "LONG" else "LONG",
            "target": fill_target, "stop_pct": abs_gap * 0.3,
            "hold_days_max": 1, "note": f"과잉 갭 {gap_pct:.1f}% 역추세",
        }

    # Gap-and-Go: 갭 2~5% + 강한 감성 + 충분한 프리마켓 거래량
    if 2.0 <= abs_gap <= 5.0 and abs(raw_score) >= 0.55 and (premarket_volume_ratio or 0) >= 3.0:
        return {
            "approved": True, "strategy": "GAP_AND_GO", "direction": direction,
            "stop_pct": 1.5, "target_pct": abs_gap * 0.5,
            "hold_days_max": 1, "note": f"갭 {gap_pct:.1f}% 추종",
        }

    return {"approved": False, "reason": "갭 조건 미충족"}
