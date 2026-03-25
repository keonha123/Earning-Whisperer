# strategies/s6_iv_crush.py — 전략 6: IV Crush / Put-Call Ratio
# 논문: Patell & Wolfson(1979), Xing et al.(2010)
# 승률: 56~65%

def evaluate_iv_crush(raw_score, put_call_ratio, iv_rank, current_iv, hours_to_earnings):
    results = {}

    # 전략 A: IV Crush 순수 매도 (방향 중립)
    iv_approved = (
        (hours_to_earnings or 0) >= 24 and (hours_to_earnings or 0) <= 48
        and (iv_rank or 0) >= 70
        and (current_iv or 0) >= 0.50
    )
    results["iv_crush_sell"] = {
        "approved": iv_approved,
        "strategy": "IV_CRUSH",
        "note":     "어닝 전날 Straddle 매도 → IV 붕괴 수익",
        "hold_days_max": 2,
    }

    # 전략 B: Put/Call Ratio 방향 베팅
    pc_approved  = False
    pc_direction = None
    if (put_call_ratio or 0) > 1.5 and raw_score > 0.50:
        pc_approved  = True
        pc_direction = "LONG"   # 과도한 풋 → 실제 긍정 뉴스 = 쇼트커버 급등
    elif (put_call_ratio or 0) < 0.50 and raw_score < -0.30:
        pc_approved  = True
        pc_direction = "SHORT"  # 과도한 콜 → 실망 매도 강함

    results["pc_ratio_contrarian"] = {
        "approved":  pc_approved,
        "strategy":  "IV_CRUSH",
        "direction": pc_direction,
        "note":      f"P/C Ratio {put_call_ratio} 극단 역베팅",
        "hold_days_max": 1,
    }

    # 승인된 전략 반환 (우선순위: iv_crush_sell > pc_ratio)
    for key in ["iv_crush_sell", "pc_ratio_contrarian"]:
        if results[key]["approved"]:
            return results[key]

    return {"approved": False, "reason": "IV/PC 조건 미충족"}
