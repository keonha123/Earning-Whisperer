# ═══════════════════════════════════════════════════════════════════════════
# strategies/s1_breakout.py  —  전략 1: 뉴스 돌파매매
# 논문: Chan(2003), Gervais et al.(2001)
# 승률: 53~58%  |  수익비: 1:2.0  |  보유: 최대 3일
# ═══════════════════════════════════════════════════════════════════════════
VALID_CATALYSTS = {"EARNINGS_BEAT", "GUIDANCE_UP", "PRODUCT_NEWS"}


def evaluate_breakout(raw_score, catalyst_type, volume_ratio,
                       current_price, ma20, high_52w,
                       first_5min_close, first_5min_open, atr14):
    c1 = raw_score >= 0.60 and catalyst_type in VALID_CATALYSTS
    c2 = (current_price > ma20 * 1.005) or (current_price > high_52w * 0.98) if (ma20 and high_52w) else False
    c3 = (volume_ratio or 0) >= 2.0
    c4 = (first_5min_close > first_5min_open) if (first_5min_close and first_5min_open) else False

    if not (c1 and c2 and c3 and c4):
        return {"approved": False, "reason": f"c1={c1},c2={c2},c3={c3},c4={c4}"}

    return {
        "approved": True, "strategy": "NEWS_BREAKOUT", "direction": "LONG",
        "stop_mult": 1.2, "target_mult": 2.4, "hold_days_max": 3,
        "note": "저항선 돌파 + 거래량 폭발",
    }
