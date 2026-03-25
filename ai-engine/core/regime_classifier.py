# ═══════════════════════════════════════════════════════════════════════════
# core/regime_classifier.py
# 시장 국면 분류 — VIX + 볼린저밴드로 Bull/Bear/Volatile 판별
# 논문 근거: Baker & Wurgler (2006) 투자자 감성 지수
# ═══════════════════════════════════════════════════════════════════════════
from typing import Optional


def classify_regime(
    vix: Optional[float],
    bb_position: Optional[float],
) -> str:
    """
    시장 국면 분류.

    Returns:
        "BULL_TREND"      — 저변동 + 가격 상단 유지
        "BEAR_TREND"      — 저변동 + 가격 하단 유지
        "HIGH_VOLATILITY" — VIX 25~35 구간
        "EXTREME_FEAR"    — VIX >= 35 (진입 금지)
        "NORMAL"          — 기본 정상 장세
    """
    if vix is None:
        return "NORMAL"

    # 극한 공포 → 모든 거래 금지
    if vix >= 35:
        return "EXTREME_FEAR"

    # 고변동성 → 포지션 50% 축소
    if vix >= 25:
        return "HIGH_VOLATILITY"

    # 저변동 장세에서 추세 판별 (볼린저밴드 위치 활용)
    if vix < 15 and bb_position is not None:
        if bb_position >= 0.70:
            return "BULL_TREND"   # 상단 밴드 유지 = 강세 추세
        if bb_position <= 0.30:
            return "BEAR_TREND"   # 하단 밴드 유지 = 약세 추세

    return "NORMAL"


def get_regime_multiplier(composite_score: float, regime: str) -> float:
    """
    시장 국면별 시그널 강도 보정계수.
    추세 방향과 일치하면 강화, 반대면 약화.
    """
    if regime == "BULL_TREND":
        return 1.15 if composite_score > 0 else 0.80
    elif regime == "BEAR_TREND":
        return 1.15 if composite_score < 0 else 0.80
    elif regime == "HIGH_VOLATILITY":
        return 0.70  # 고변동성 전체 약화
    return 1.00
