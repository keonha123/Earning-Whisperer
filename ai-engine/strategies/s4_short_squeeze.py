# strategies/s4_short_squeeze.py — 전략 4: Short Squeeze 감지
# 논문: Engelberg et al.(2012), Asquith et al.(2005)
# 승률: 55~62%

def detect_short_squeeze_setup(raw_score, catalyst_type, volume_ratio,
                                price_change_pct, bb_position,
                                days_to_cover, short_interest_pct):
    # Short Interest 근사: 데이터 없으면 volume_ratio로 대체
    high_short = (short_interest_pct >= 5.0) if short_interest_pct is not None else (volume_ratio or 0) >= 4.0
    squeeze_pressure = (days_to_cover >= 5.0) if days_to_cover is not None else (volume_ratio or 0) >= 3.0

    valid_cats = {"EARNINGS_BEAT", "GUIDANCE_UP", "PRODUCT_NEWS"}
    strong_positive = raw_score >= 0.65 and catalyst_type in valid_cats
    initial_surge   = (price_change_pct or 0) > 3.0
    squeeze_start   = bb_position is not None and bb_position < 0.30

    approved = strong_positive and high_short and squeeze_pressure and (initial_surge or squeeze_start)

    return {
        "approved":  approved,
        "strategy":  "SHORT_SQUEEZE",
        "direction": "LONG",
        "hold_days_max": 3,
        "note": "공매도 커버링 + 뉴스 매수 겹침",
    }
