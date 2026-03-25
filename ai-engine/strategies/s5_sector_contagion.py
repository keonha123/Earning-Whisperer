# strategies/s5_sector_contagion.py — 전략 5: 섹터 연쇄 파급
# 논문: Ramnath(2002), Thomas & Zhang(2008)
# 승률: 52~57%

SECTOR_MAP = {
    "NVDA": {"suppliers": ["TSM"], "competitors": ["AMD","INTC","QCOM"], "adjacent": ["SMCI"]},
    "AAPL": {"suppliers": ["QCOM","AVGO","SWKS"],  "competitors": ["GOOG","MSFT"], "adjacent": ["SPOT","NFLX"]},
    "JPM":  {"suppliers": [], "competitors": ["BAC","WFC","GS","MS"], "adjacent": ["V","MA"]},
    "AMZN": {"suppliers": [], "competitors": ["MSFT","GOOG"], "adjacent": ["FDX","UPS"]},
    "MSFT": {"suppliers": [], "competitors": ["GOOG","AMZN"], "adjacent": []},
}

def evaluate_sector_contagion(primary_ticker, primary_raw_score, primary_catalyst,
                               secondary_ticker, secondary_price_change_pct, hours_since_primary_news):
    if primary_ticker not in SECTOR_MAP:
        return {"approved": False, "reason": "섹터 매핑 없음"}

    sector       = SECTOR_MAP[primary_ticker]
    relationship = None
    for rel_type, tickers in sector.items():
        if secondary_ticker in tickers:
            relationship = rel_type
            break

    if not relationship:
        return {"approved": False, "reason": "관련 기업 아님"}
    if abs(primary_raw_score) < 0.55:
        return {"approved": False, "reason": f"1차 신호 약함 ({primary_raw_score:.2f})"}
    if not (2.0 <= (hours_since_primary_news or 0) <= 8.0):
        return {"approved": False, "reason": f"타이밍 미달 ({hours_since_primary_news}시간)"}

    expected_secondary = primary_raw_score * 0.4 * 100
    underreacted       = abs(secondary_price_change_pct or 0) < abs(expected_secondary) * 0.5
    direction          = "LONG" if primary_raw_score > 0 else "SHORT"
    if relationship == "competitors":
        direction = "SHORT" if direction == "LONG" else "LONG"

    return {
        "approved":     underreacted,
        "strategy":     "SECTOR_CONTAGION",
        "direction":    direction,
        "relationship": relationship,
        "hold_days_max":2,
        "expected_move_pct": round(expected_secondary, 2),
        "note": f"{primary_ticker} 어닝 → {secondary_ticker} 2차 반응 미반영",
    }
