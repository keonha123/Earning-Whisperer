from __future__ import annotations

from dataclasses import dataclass
import math

try:
    from models.request_models import MarketData
    from models.signal_models import StrategyName
except ImportError:  # pragma: no cover
    from ..models.request_models import MarketData
    from ..models.signal_models import StrategyName


_CATALYST_STRENGTH = {
    "EARNINGS_BEAT": 1.00,
    "GUIDANCE_UP": 0.96,
    "PRODUCT_NEWS": 0.78,
    "OPERATIONAL_EXEC": 0.72,
    "GUIDANCE_HOLD": 0.45,
    "MACRO_COMMENTARY": 0.32,
    "RESTRUCTURING": 0.28,
    "REGULATORY_RISK": 0.10,
    "EARNINGS_MISS": 0.08,
    "GUIDANCE_DOWN": 0.06,
    "UNCLASSIFIED": 0.25,
}


@dataclass(frozen=True)
class EventQualityBreakdown:
    total: float
    catalyst: float
    surprise: float
    revisions: float
    freshness: float
    trend: float
    breakout: float
    volume: float
    extension_penalty: float
    volatility_penalty: float

    def to_dict(self) -> dict[str, float]:
        return {
            "total": round(self.total, 4),
            "catalyst": round(self.catalyst, 4),
            "surprise": round(self.surprise, 4),
            "revisions": round(self.revisions, 4),
            "freshness": round(self.freshness, 4),
            "trend": round(self.trend, 4),
            "breakout": round(self.breakout, 4),
            "volume": round(self.volume, 4),
            "extension_penalty": round(self.extension_penalty, 4),
            "volatility_penalty": round(self.volatility_penalty, 4),
        }


def score_event_quality(
    market_data: MarketData | None,
    analysis: dict | None,
    *,
    strategy: StrategyName,
) -> EventQualityBreakdown:
    if market_data is None:
        return EventQualityBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    catalyst_type = str((analysis or {}).get("catalyst_type") or "UNCLASSIFIED").upper()
    catalyst = _CATALYST_STRENGTH.get(catalyst_type, 0.25)
    surprise = _scaled_positive(market_data.surprise_pct, low=2.0, high=18.0, default=0.45)
    revisions = _scaled_positive(market_data.analyst_revision_delta_pct, low=0.0, high=8.0, default=0.45)
    freshness = _freshness_score(market_data.hours_since_news)
    trend = _trend_score(market_data)
    breakout = _breakout_score(market_data)
    volume = _volume_score(market_data)
    extension_penalty = _extension_penalty(market_data)
    volatility_penalty = _volatility_penalty(market_data)

    if strategy == StrategyName.GAP_AND_GO:
        total = (
            catalyst * 0.16
            + surprise * 0.14
            + revisions * 0.08
            + freshness * 0.14
            + trend * 0.16
            + breakout * 0.08
            + volume * 0.24
            - extension_penalty * 0.14
            - volatility_penalty * 0.16
        )
    elif strategy == StrategyName.PEAD:
        total = (
            catalyst * 0.18
            + surprise * 0.20
            + revisions * 0.14
            + freshness * 0.08
            + trend * 0.14
            + breakout * 0.10
            + volume * 0.14
            - extension_penalty * 0.10
            - volatility_penalty * 0.08
        )
    else:
        total = (
            catalyst * 0.22
            + surprise * 0.16
            + revisions * 0.10
            + freshness * 0.12
            + trend * 0.14
            + breakout * 0.12
            + volume * 0.18
            - extension_penalty * 0.10
            - volatility_penalty * 0.12
        )

    total = _clamp(total)
    return EventQualityBreakdown(
        total=total,
        catalyst=catalyst,
        surprise=surprise,
        revisions=revisions,
        freshness=freshness,
        trend=trend,
        breakout=breakout,
        volume=volume,
        extension_penalty=extension_penalty,
        volatility_penalty=volatility_penalty,
    )


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _percentage_points(value: float | None) -> float:
    if value is None:
        return 0.0
    numeric = float(value)
    return numeric * 100.0 if abs(numeric) <= 1.0 else numeric


def _scaled_positive(value: float | None, *, low: float, high: float, default: float) -> float:
    if value is None:
        return default
    if high <= low:
        return default
    return _clamp((float(value) - low) / (high - low))


def _freshness_score(hours_since_news: float | None) -> float:
    if hours_since_news is None:
        return 0.55
    hours = float(hours_since_news)
    if hours <= 6.0:
        return 1.0
    if hours <= 24.0:
        return 0.86
    if hours <= 48.0:
        return 0.62
    if hours <= 72.0:
        return 0.38
    return 0.18


def _trend_score(market_data: MarketData) -> float:
    scores: list[float] = []
    relative_strength_points = _percentage_points(market_data.relative_strength_20d)
    if market_data.current_price and market_data.ma20:
        scores.append(1.0 if market_data.current_price > market_data.ma20 else 0.0)
    if market_data.current_price and market_data.ma50:
        scores.append(1.0 if market_data.current_price > market_data.ma50 else 0.0)
    if market_data.current_price and market_data.ma200:
        scores.append(1.0 if market_data.current_price > market_data.ma200 else 0.0)
    if market_data.ma_stack_bullish is not None:
        scores.append(1.0 if market_data.ma_stack_bullish else 0.0)
    if market_data.ichimoku_weekly_cloud_score is not None:
        scores.append(_clamp((float(market_data.ichimoku_weekly_cloud_score) + 1.0) / 2.0))
    if market_data.spy_relative_strength_20d is not None:
        scores.append(_clamp((float(market_data.spy_relative_strength_20d) + 8.0) / 16.0))
    if market_data.qqq_relative_strength_20d is not None:
        scores.append(_clamp((float(market_data.qqq_relative_strength_20d) + 8.0) / 16.0))
    scores.append(_clamp((relative_strength_points + 10.0) / 20.0))
    return sum(scores) / len(scores) if scores else 0.5


def _breakout_score(market_data: MarketData) -> float:
    scores: list[float] = []
    if market_data.breakout_20d_pct is not None:
        scores.append(_clamp((float(market_data.breakout_20d_pct) + 0.01) / 0.08))
    if market_data.current_price and market_data.high_52w and market_data.high_52w > 0:
        distance = (float(market_data.current_price) / float(market_data.high_52w)) - 1.0
        scores.append(_clamp((distance + 0.25) / 0.25))
    return sum(scores) / len(scores) if scores else 0.5


def _volume_score(market_data: MarketData) -> float:
    scores: list[float] = []
    if market_data.volume_ratio is not None:
        scores.append(_clamp((float(market_data.volume_ratio) - 1.0) / 3.0))
    if market_data.volume_zscore_20d is not None:
        scores.append(_clamp((float(market_data.volume_zscore_20d) + 0.5) / 3.0))
    if market_data.liquidity_score is not None:
        scores.append(_clamp(float(market_data.liquidity_score)))
    return sum(scores) / len(scores) if scores else 0.5


def _extension_penalty(market_data: MarketData) -> float:
    penalties: list[float] = []
    if market_data.rsi_14 is not None:
        penalties.append(_clamp((float(market_data.rsi_14) - 70.0) / 15.0))
    if market_data.stochastic_k is not None:
        penalties.append(_clamp((float(market_data.stochastic_k) - 80.0) / 15.0))
    if market_data.bb_position is not None:
        penalties.append(_clamp((float(market_data.bb_position) - 0.90) / 0.10))
    if market_data.gap_pct is not None:
        penalties.append(_clamp((abs(float(market_data.gap_pct)) - 6.0) / 8.0))
    return sum(penalties) / len(penalties) if penalties else 0.0


def _volatility_penalty(market_data: MarketData) -> float:
    penalties: list[float] = []
    if market_data.realized_vol_10d is not None:
        penalties.append(_clamp((float(market_data.realized_vol_10d) - 0.35) / 0.30))
    if market_data.vix is not None:
        penalties.append(_clamp((float(market_data.vix) - 24.0) / 12.0))
    if market_data.bb_bandwidth is not None:
        penalties.append(_clamp((float(market_data.bb_bandwidth) - 0.18) / 0.20))
    return sum(penalties) / len(penalties) if penalties else 0.0


__all__ = ["EventQualityBreakdown", "score_event_quality"]
