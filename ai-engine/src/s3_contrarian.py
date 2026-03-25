# strategies/s3_contrarian.py — 전략 3: 역추세
# 논문: De Bondt & Thaler(1985), Tetlock et al.(2008)
# 승률: 51~56%

def detect_overreaction(raw_score, price_change_pct, rsi_14, bb_position, volume_ratio, hours_since_news):
    if not price_change_pct:
        return {"approved": False, "reason": "price_change_pct 없음"}

    expected_move  = abs(raw_score) * 5.0
    overreaction   = abs(price_change_pct) / expected_move >= 2.5 if expected_move > 0 else False
    rsi_extreme    = rsi_14 is not None and (rsi_14 > 78 or rsi_14 < 22)
    timing_ok      = 1.0 <= (hours_since_news or 0) <= 4.0

    if price_change_pct > 0 and raw_score < 0.50:
        reversal_dir = "SHORT"
    elif price_change_pct < 0 and raw_score > -0.50:
        reversal_dir = "LONG"
    else:
        reversal_dir = None

    approved = overreaction and rsi_extreme and reversal_dir and timing_ok

    return {
        "approved": approved, "strategy": "CONTRARIAN",
        "direction": reversal_dir, "hold_days_max": 2,
        "target_return_pct": round(price_change_pct * -0.40, 2),
        "note": f"과잉반응 비율={abs(price_change_pct)/expected_move:.1f}x" if expected_move > 0 else "",
    }
