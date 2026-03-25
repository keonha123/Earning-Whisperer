# core/risk_manager.py
# ATR 기반 손절/익절 + Half-Kelly 포지션 사이징
# 수익비 목표: MODERATE=1:1.67, STRONG=1:2.0
from typing import Optional
from config import settings


def calculate_exit_levels(
    entry_price:     float,
    atr_14:          float,
    composite_score: float,
    signal_strength: str,    # "STRONG" | "MODERATE" | "WEAK"
    direction:       str,    # "LONG" | "SHORT"
) -> dict:
    """
    ATR 기반 손절/익절 계산.

    신호 강도별 ATR 배수:
      STRONG:   손절 1.5×ATR, 익절 3.0×ATR (수익비 1:2.0)
      MODERATE: 손절 1.2×ATR, 익절 2.0×ATR (수익비 1:1.67)
      WEAK:     손절 1.0×ATR, 익절 1.5×ATR (수익비 1:1.5)
    """
    if entry_price <= 0 or atr_14 <= 0:
        return {}

    if signal_strength == "STRONG":
        stop_mult   = settings.strong_stop_atr    # 1.5
        target_mult = settings.strong_target_atr  # 3.0
    elif signal_strength == "MODERATE":
        stop_mult   = settings.stop_atr_mult      # 1.2
        target_mult = settings.target_atr_mult    # 2.0
    else:  # WEAK
        stop_mult   = 1.0
        target_mult = 1.5

    if direction == "LONG":
        stop_loss   = entry_price - (atr_14 * stop_mult)
        take_profit = entry_price + (atr_14 * target_mult)
    else:  # SHORT
        stop_loss   = entry_price + (atr_14 * stop_mult)
        take_profit = entry_price - (atr_14 * target_mult)

    risk_pct   = abs(entry_price - stop_loss)   / entry_price * 100
    reward_pct = abs(take_profit - entry_price) / entry_price * 100

    return {
        "stop_loss":     round(stop_loss,   2),
        "take_profit":   round(take_profit, 2),
        "risk_pct":      round(risk_pct,    2),
        "reward_pct":    round(reward_pct,  2),
        "profit_factor": round(target_mult / stop_mult, 2),
    }


def calculate_kelly_position(
    composite_score: float,
    confidence:      float,
    vix:             Optional[float],
) -> float:
    """
    Half-Kelly Criterion 포지션 사이징.

    공식:
      f* = (b×p - q) / b  × 0.5  (Half-Kelly)
      b = 기대 수익/손실 비율
      p = 승률 (confidence 기반)
      q = 1 - p

    Returns:
        포트폴리오 대비 포지션 비율 (0.0 ~ kelly_max_position)
    """
    # 중립 구간 → 진입 안함
    if abs(composite_score) < 0.20:
        return 0.0

    # 기대 수익비 추정 (composite 강도 기반)
    b = 1.5 + abs(composite_score)  # 최소 1:1.5, 최대 1:2.5

    # 승률 = confidence (0.5~0.95 범위로 압축)
    p = 0.5 + (confidence - 0.5) * 0.9
    q = 1.0 - p

    # Kelly 공식
    kelly_f = ((b * p - q) / b) * 0.5  # Half-Kelly (전체의 50%만)

    # VIX 보정
    if vix is not None:
        if vix >= 30:   kelly_f *= 0.50
        elif vix >= 25: kelly_f *= 0.70

    # 최대 포지션 캡
    return round(max(0.0, min(kelly_f, settings.kelly_max_position)), 4)
