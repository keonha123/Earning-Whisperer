"""
core/risk_manager.py — EarningWhisperer AI Engine v3.1.0
Half-Kelly 포지션 사이징 + ATR 기반 손절/익절 계산 모듈

Half-Kelly 공식:
  b  = 1.5 + |composite_score|      (기대 수익비, 1.5~2.5)
  p  = 0.5 + (confidence - 0.5) × 0.9  (승률 추정, 압축)
  q  = 1 - p
  f* = ((b×p - q) / b) × 0.5        (Half-Kelly)
  VIX 보정: VIX≥30 → ×0.50, VIX≥25 → ×0.70
  최대 캡: KELLY_MAX_POSITION (기본 25%)

ATR 손절/익절:
  STRONG   (|adj| ≥ 0.70): 손절=1.5×ATR, 익절=3.0×ATR (수익비 2.00)
  MODERATE (|adj| ≥ 0.50): 손절=1.2×ATR, 익절=2.0×ATR (수익비 1.67)
  WEAK     (|adj|  < 0.50): 손절=1.0×ATR, 익절=1.5×ATR (수익비 1.50)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config import get_settings
from ..models.request_models import MarketData
from ..models.signal_models import SignalStrength

logger = logging.getLogger(__name__)


# ── ATR 배수 테이블 ──────────────────────────────────────────────────────────
_ATR_CONFIG = {
    SignalStrength.STRONG:   {"stop": 1.5, "target": 3.0, "profit_factor": 2.00},
    SignalStrength.MODERATE: {"stop": 1.2, "target": 2.0, "profit_factor": 1.67},
    SignalStrength.WEAK:     {"stop": 1.0, "target": 1.5, "profit_factor": 1.50},
}


@dataclass
class RiskParameters:
    """리스크 관리 파라미터 결과."""

    position_pct: float
    signal_strength: SignalStrength
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
    stop_loss_pct: Optional[float]
    take_profit_pct: Optional[float]
    profit_factor: float


def determine_signal_strength(adj_composite: float) -> SignalStrength:
    """adj_composite 절댓값으로 신호 강도를 결정합니다."""
    abs_adj = abs(adj_composite)
    if abs_adj >= 0.70:
        return SignalStrength.STRONG
    elif abs_adj >= 0.50:
        return SignalStrength.MODERATE
    else:
        return SignalStrength.WEAK


def calculate_position_size(
    adj_composite: float,
    confidence: float,
    market_data: Optional[MarketData],
) -> float:
    """Half-Kelly 공식으로 포지션 크기를 계산합니다.

    Args:
        adj_composite: 국면 보정된 복합 점수 (-1.0 ~ +1.0)
        confidence:    Gemini 신뢰도 (0.0 ~ 1.0)
        market_data:   VIX 보정에 사용

    Returns:
        포지션 비율 (0.0 ~ KELLY_MAX_POSITION)
    """
    settings = get_settings()
    if abs(adj_composite) < 1e-9:
        return 0.0

    # 기대 수익비 b: 1.5 ~ 2.5 (composite 강도에 따라)
    b = 1.5 + abs(adj_composite)

    # 승률 추정 p: confidence를 0.5 기준으로 압축
    p = 0.5 + (confidence - 0.5) * 0.9
    p = float(np.clip(p, 0.01, 0.99))
    q = 1.0 - p

    # Half-Kelly
    kelly_f = ((b * p - q) / b) * 0.5

    # VIX 동적 보정
    vix = market_data.vix if market_data else None
    if vix is not None:
        if vix >= 30.0:
            kelly_f *= 0.50
            logger.debug("VIX=%.1f ≥ 30 → Kelly ×0.50", vix)
        elif vix >= 25.0:
            kelly_f *= 0.70
            logger.debug("VIX=%.1f ≥ 25 → Kelly ×0.70", vix)

    position = float(np.clip(kelly_f, 0.0, settings.kelly_max_position))
    logger.debug("Kelly 포지션: %.1f%% (b=%.2f, p=%.2f, q=%.2f)", position * 100, b, p, q)
    return position


def calculate_stop_take_profit(
    signal_strength: SignalStrength,
    current_price: Optional[float],
    atr_14: Optional[float],
    is_long: bool,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], float]:
    """ATR 기반 손절/익절 가격을 계산합니다.

    Returns:
        (stop_loss_price, take_profit_price, stop_loss_pct, take_profit_pct, profit_factor)
    """
    config = _ATR_CONFIG[signal_strength]
    profit_factor = config["profit_factor"]

    if current_price is None or atr_14 is None or atr_14 <= 0:
        return None, None, None, None, profit_factor

    stop_dist   = atr_14 * config["stop"]
    target_dist = atr_14 * config["target"]

    if is_long:
        stop_loss_price   = current_price - stop_dist
        take_profit_price = current_price + target_dist
    else:
        stop_loss_price   = current_price + stop_dist
        take_profit_price = current_price - target_dist

    stop_loss_pct   = round(stop_dist   / current_price * 100, 2)
    take_profit_pct = round(target_dist / current_price * 100, 2)

    return (
        round(stop_loss_price, 2),
        round(take_profit_price, 2),
        stop_loss_pct,
        take_profit_pct,
        profit_factor,
    )


def calculate_risk_parameters(
    adj_composite: float,
    confidence: float,
    market_data: Optional[MarketData],
) -> RiskParameters:
    """통합 리스크 파라미터를 계산합니다."""
    signal_strength = determine_signal_strength(adj_composite)
    position_pct    = calculate_position_size(adj_composite, confidence, market_data)
    is_long         = adj_composite >= 0.0

    current_price = market_data.current_price if market_data else None
    atr_14        = market_data.atr_14        if market_data else None

    (
        stop_loss_price,
        take_profit_price,
        stop_loss_pct,
        take_profit_pct,
        profit_factor,
    ) = calculate_stop_take_profit(signal_strength, current_price, atr_14, is_long)

    return RiskParameters(
        position_pct=position_pct,
        signal_strength=signal_strength,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        profit_factor=profit_factor,
    )
