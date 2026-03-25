# core/integrity_validator.py
# 방향-해설 일관성 검증 — Gemini 환각 감지
# raw_score가 음수인데 rationale에 긍정 키워드가 많으면 환각으로 판정

POSITIVE_KEYWORDS = [
    "성장", "증가", "상회", "긍정", "강세", "개선", "record", "growth",
    "beat", "exceed", "outperform", "record", "surge", "strong", "raise",
]
NEGATIVE_KEYWORDS = [
    "감소", "하락", "우려", "부정", "약세", "악화", "miss", "decline",
    "risk", "slow", "pressure", "cut", "loss", "weak", "reduce",
]


def validate_direction_consistency(raw_score: float, rationale: str) -> bool:
    """
    raw_score 방향과 rationale 내용이 일치하는지 검증.

    중립 범위 (-0.2 ~ +0.2): 검증 면제
    긍정 점수 (> +0.2): rationale에 부정 키워드가 압도적으로 많으면 환각
    부정 점수 (< -0.2): rationale에 긍정 키워드가 압도적으로 많으면 환각

    Returns:
        True = 일관성 OK
        False = 환각 의심 → 재호출 필요
    """
    # 중립 범위는 검증 면제
    if -0.2 <= raw_score <= 0.2:
        return True

    rationale_lower = rationale.lower()
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in rationale_lower)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in rationale_lower)

    if raw_score > 0.2:
        # 긍정 점수인데 부정 키워드가 2개 이상 더 많으면 환각
        if neg_count > pos_count + 2:
            return False

    elif raw_score < -0.2:
        # 부정 점수인데 긍정 키워드가 2개 이상 더 많으면 환각
        if pos_count > neg_count + 2:
            return False

    return True
