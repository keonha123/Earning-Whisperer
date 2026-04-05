"""Execution-style recommendation logic for earnings-event trading."""

from __future__ import annotations

from dataclasses import dataclass

from models.request_models import MarketData, SectionType
from models.signal_models import StrategyName


@dataclass(frozen=True)
class StyleRecommendation:
    style: str
    max_trades_per_session: int
    max_holding_minutes: int
    rationale: str


def recommend_execution_style(
    *,
    strategy: StrategyName,
    composite_score: float,
    confidence: float,
    trade_approved: bool,
    market_data: MarketData | None,
    section_type: SectionType | None = None,
) -> StyleRecommendation:
    """Recommend a trading horizon and trade frequency for the signal."""

    if not trade_approved or abs(composite_score) < 0.55:
        return StyleRecommendation(
            style="NO_TRADE",
            max_trades_per_session=0,
            max_holding_minutes=0,
            rationale="Signal quality is below the execution threshold.",
        )

    spread = market_data.bid_ask_spread_bps if market_data else None
    liquidity = market_data.liquidity_score if market_data else None
    volume_ratio = market_data.volume_ratio if market_data else None
    gap_pct = market_data.gap_pct if market_data else None

    ultra_liquid = (spread is not None and spread <= 12) or (liquidity is not None and liquidity >= 0.9)
    elevated_volume = volume_ratio is not None and volume_ratio >= 2.5

    if (
        strategy in {StrategyName.GAP_AND_GO, StrategyName.NEWS_BREAKOUT}
        and ultra_liquid
        and elevated_volume
        and gap_pct is not None
        and abs(gap_pct) >= 2.0
    ):
        return StyleRecommendation(
            style="INTRADAY_EVENT",
            max_trades_per_session=2,
            max_holding_minutes=240,
            rationale="Fast post-earnings price discovery with high liquidity supports intraday event trading.",
        )

    if (
        strategy in {StrategyName.SHORT_SQUEEZE, StrategyName.SECTOR_CONTAGION, StrategyName.WHISPER_PLAY}
        or abs(composite_score) >= 0.72
        or section_type == SectionType.Q_AND_A
    ):
        return StyleRecommendation(
            style="EVENT_SWING",
            max_trades_per_session=1,
            max_holding_minutes=3 * 24 * 60,
            rationale="Signal is better suited to post-event drift capture over one to three trading days.",
        )

    if ultra_liquid and confidence >= 0.9:
        return StyleRecommendation(
            style="SCALP",
            max_trades_per_session=3,
            max_holding_minutes=45,
            rationale="Only ultra-liquid names qualify for short-horizon scalps; this is not HFT.",
        )

    return StyleRecommendation(
        style="EVENT_SWING",
        max_trades_per_session=1,
        max_holding_minutes=2 * 24 * 60,
        rationale="Default to lower-frequency event swing trading rather than HFT.",
    )

