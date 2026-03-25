# strategies/s7_whisper.py — 전략 7: 어닝 위스퍼 비교
# 논문: Bagnoli et al.(1999), Bhattacharya(2001)
# 승률: 53~59%

def apply_whisper_adjustment(raw_score, whisper_signal, earnings_surprise_pct):
    """
    위스퍼 신호에 따라 raw_score 조정 + 역추세 신호 생성.

    BELOW_WHISPER + 컨센서스 비트 → 점수 하향 + SHORT 역추세 기회
    ABOVE_WHISPER + 컨센서스 미달 → 점수 상향 (과도한 하락 반응 완화)
    """
    if whisper_signal == "BELOW_WHISPER" and raw_score > 0.30:
        adjusted = raw_score * 0.60  # 40% 하향
        contrarian = "SHORT" if raw_score > 0.50 else None
        return {
            "adjusted_raw_score": round(adjusted, 4),
            "whisper_penalty":    True,
            "contrarian_signal":  contrarian,
            "strategy":           "WHISPER_PLAY",
            "note": "컨센서스 비트 but 위스퍼 미달 — 실망 매도 가능성",
            "hold_days_max": 1,
        }
    elif whisper_signal == "ABOVE_WHISPER" and raw_score < -0.30:
        adjusted = raw_score * 0.50  # 50% 중화 (예상보다 양호)
        return {
            "adjusted_raw_score": round(adjusted, 4),
            "whisper_bonus":      True,
            "contrarian_signal":  None,
            "strategy":           "WHISPER_PLAY",
            "note": "컨센서스 미달 but 위스퍼 비트 — 반등 가능성",
            "hold_days_max": 1,
        }

    return {
        "adjusted_raw_score": raw_score,
        "whisper_penalty":    False,
        "contrarian_signal":  None,
        "note": "위스퍼 조정 없음",
    }
