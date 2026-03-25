# ═══════════════════════════════════════════════════════════════════════════
# core/pead_calculator.py
# PEAD (Post-Earnings Announcement Drift) 전략 — SUE 점수 계산
# 논문: Bernard & Thomas (1992), Ball & Brown (1968)
#
# SUE = Standardized Unexpected Earnings
# = (실제EPS - 예상EPS) / σ_EPS
# σ_EPS가 없으면 earnings_surprise_pct / 10으로 근사
#
# 승률 기여: 방향 일치 시 +3~5%p
# PEAD 진입 조건: |SUE| > 2.0 + 감성 방향 일치
# ═══════════════════════════════════════════════════════════════════════════
from typing import Optional


def calculate_sue(
    earnings_surprise_pct: Optional[float],
    raw_score_sign: float,  # +1.0 또는 -1.0 (raw_score 방향)
) -> float:
    """
    SUE 점수 계산 (-5.0 ~ +5.0).

    Args:
        earnings_surprise_pct: (실제EPS - 예상EPS) / |예상EPS| × 100
                               예: +15.2 = 컨센서스 15.2% 상회
        raw_score_sign: Gemini 감성 방향 (+1.0=긍정, -1.0=부정)

    Returns:
        sue_score: -5.0 ~ +5.0
        - |sue_score| > 2.0 = 강한 PEAD 신호 (드리프트 진입 조건)
        - 방향 불일치 시 50% 약화 (혼재 신호)
    """
    # 데이터 없음 → 감성 기반 보수적 추정
    if earnings_surprise_pct is None:
        return raw_score_sign * 0.5

    # 기본 SUE: EPS 서프라이즈 % / 10 (단위 정규화)
    # 예: +20% 서프라이즈 → SUE = 2.0
    sue_raw = earnings_surprise_pct / 10.0

    # 방향 불일치 처리 (SUE와 Gemini 감성이 반대 방향)
    # |SUE| < 1.0 이면 방향 불일치 허용 (신호 약함)
    sue_sign = 1.0 if sue_raw > 0 else (-1.0 if sue_raw < 0 else 0.0)
    if sue_sign != raw_score_sign and abs(sue_raw) >= 1.0:
        # 강한 방향 충돌 → 50% 약화 (혼재 신호로 신뢰도 감소)
        sue_raw *= 0.5

    # -5.0 ~ +5.0 클리핑
    return round(max(-5.0, min(5.0, sue_raw)), 4)
