"""Market regime classification and score adjustment helpers."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from models.request_models import MarketData
from models.signal_models import MarketRegime

logger = logging.getLogger(__name__)

_REGIME_MULTIPLIER = {
    (MarketRegime.BULL_TREND, True): 1.15,
    (MarketRegime.BULL_TREND, False): 0.80,
    (MarketRegime.BEAR_TREND, True): 0.80,
    (MarketRegime.BEAR_TREND, False): 1.15,
    (MarketRegime.HIGH_VOLATILITY, True): 0.70,
    (MarketRegime.HIGH_VOLATILITY, False): 0.70,
    (MarketRegime.EXTREME_FEAR, True): 0.00,
    (MarketRegime.EXTREME_FEAR, False): 0.00,
    (MarketRegime.NORMAL, True): 1.00,
    (MarketRegime.NORMAL, False): 1.00,
}


def classify_regime(market_data: Optional[MarketData]) -> MarketRegime:
    """Classify the current market regime from VIX and Bollinger position."""

    if market_data is None:
        return MarketRegime.NORMAL

    vix = market_data.vix
    bb = market_data.bb_position

    if vix is None:
        return MarketRegime.NORMAL
    if vix >= 35.0:
        logger.warning("EXTREME_FEAR detected: VIX=%.1f", vix)
        return MarketRegime.EXTREME_FEAR
    if vix >= 25.0:
        logger.info("HIGH_VOLATILITY detected: VIX=%.1f", vix)
        return MarketRegime.HIGH_VOLATILITY

    if vix < 15.0 and bb is not None:
        if bb >= 0.70:
            return MarketRegime.BULL_TREND
        if bb <= 0.30:
            return MarketRegime.BEAR_TREND

    return MarketRegime.NORMAL


def apply_regime_multiplier(
    composite_score: float,
    regime: MarketRegime,
) -> float:
    """Apply the regime multiplier to the already-computed composite score."""

    is_positive = composite_score >= 0.0
    multiplier = _REGIME_MULTIPLIER.get((regime, is_positive), 1.0)
    adj = composite_score * multiplier
    return float(np.clip(adj, -1.0, 1.0))


def get_regime_description(regime: MarketRegime) -> str:
    """Return a user-readable description of the regime."""

    descriptions = {
        MarketRegime.BULL_TREND: "Bull trend (low VIX, upper Bollinger regime)",
        MarketRegime.BEAR_TREND: "Bear trend (low VIX, lower Bollinger regime)",
        MarketRegime.HIGH_VOLATILITY: "High volatility (VIX 25-35, reduced sizing)",
        MarketRegime.EXTREME_FEAR: "Extreme fear (VIX >= 35, no-trade regime)",
        MarketRegime.NORMAL: "Normal regime",
    }
    return descriptions.get(regime, "Unknown regime")
