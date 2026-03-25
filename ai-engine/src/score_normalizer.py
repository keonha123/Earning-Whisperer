# ═══════════════════════════════════════════════════════════════════════════
# core/score_normalizer.py
# Gemini 출력(direction/magnitude/confidence/euphemisms) → raw_score (-1~+1)
# 논문 근거: Tetlock(2007) negative_word_ratio 패널티 포함
# ═══════════════════════════════════════════════════════════════════════════
from typing import List


def normalize_score(
    direction: str,
    magnitude: float,
    confidence: float,
    euphemisms: List[dict],
    negative_word_ratio: float = 0.0,
) -> float:
    """
    Gemini 감성 출력 → raw_score (-1.0 ~ +1.0)

    공식:
      sign × magnitude × confidence
      + Σ(euphemism_penalties)    ← 항상 음수
      + tetlock_penalty           ← 부정어 밀도 높으면 추가 페널티
    """
    # 방향 부호: POSITIVE=+1, NEGATIVE=-1, NEUTRAL=0
    sign = 1.0 if direction == "POSITIVE" else (-1.0 if direction == "NEGATIVE" else 0.0)

    # 기본 점수 = 부호 × 강도 × 신뢰도
    base_score = sign * magnitude * confidence

    # 완곡어법 패널티 합산 (방향 무관, 항상 음수)
    euph_penalty = sum(float(e.get("penalty", 0.0)) for e in (euphemisms or []))

    # Tetlock(2007) 부정어 밀도 패널티
    # negative_word_ratio > 0.08 = 부정어가 전체 단어의 8% 이상 → -0.10
    tetlock_penalty = -0.10 if (negative_word_ratio or 0.0) > 0.08 else 0.0

    # 최종 점수 = 기본 + 완곡어법 패널티 + Tetlock 패널티
    final = base_score + euph_penalty + tetlock_penalty

    # -1.0 ~ +1.0 클리핑
    return round(max(-1.0, min(1.0, final)), 4)
