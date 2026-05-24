from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

try:
    from models.canonical_models import CanonicalEventBundle, CanonicalSourceHealth
    from models.evidence_models import EvidenceDocument
except ImportError:  # pragma: no cover
    from .canonical_models import CanonicalEventBundle, CanonicalSourceHealth
    from .evidence_models import EvidenceDocument


class SectionType(str, Enum):
    PREPARED_REMARKS = "PREPARED_REMARKS"
    Q_AND_A = "Q_AND_A"
    GUIDANCE = "GUIDANCE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class SourceType(str, Enum):
    EARNINGS_CALL = "EARNINGS_CALL"
    NEWS = "NEWS"
    SOCIAL = "SOCIAL"
    FILING = "FILING"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class MarketData(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    ticker: str | None = Field(default=None)
    current_price: float = Field(default=0.0)
    prev_close: float | None = Field(default=None)
    day_change_pct: float = Field(default=0.0, validation_alias="price_change_pct")
    volume_ratio: float = Field(default=1.0)
    premarket_volume_ratio: float | None = Field(default=None)
    avg_volume_20d: float | None = Field(default=None)
    recent_volume: float | None = Field(default=None)
    vix: float = Field(default=18.0)
    gap_pct: float = Field(default=0.0)
    day1_return_pct: float = Field(default=0.0)
    post_earnings_drift_pct: float = Field(default=0.0)
    iv_rank: float = Field(default=50.0)
    implied_move_pct: float | None = Field(default=None)
    bid_ask_spread_bps: float | None = Field(default=None)
    short_interest_pct_float: float = Field(default=0.0, validation_alias="short_interest_pct")
    float_rotation: float = Field(default=0.0)
    rv20: float = Field(default=0.0)
    beta_20d: float = Field(default=1.0)
    relative_strength_20d: float = Field(default=0.0)
    sector_momentum: float = Field(default=0.0)
    surprise_pct: float = Field(default=0.0, validation_alias="earnings_surprise_pct")
    whisper_eps: float | None = Field(default=None)
    avg_analyst_estimate: float | None = Field(default=None)
    next_earnings_days: Optional[int] = Field(default=None)
    rsi_14: float | None = Field(default=None)
    macd_signal: float | None = Field(default=None)
    liquidity_score: float | None = Field(default=None)
    put_call_ratio: float | None = Field(default=None)
    current_iv: float | None = Field(default=None)
    days_to_cover: float | None = Field(default=None)
    analyst_revision_delta_pct: float | None = Field(default=None)
    hours_since_news: float | None = Field(default=None)
    realized_vol_10d: float | None = Field(default=None)
    atr_pct_14: float | None = Field(default=None)
    atr_14: float | None = Field(default=None)
    breakout_20d_pct: float | None = Field(default=None)
    high_52w: float | None = Field(default=None)
    low_52w: float | None = Field(default=None)
    ma20: float | None = Field(default=None)
    ma50: float | None = Field(default=None)
    ma200: float | None = Field(default=None)
    ma_stack_bullish: bool | None = Field(default=None)
    bb_position: float | None = Field(default=None)
    bb_bandwidth: float | None = Field(default=None)
    stochastic_k: float | None = Field(default=None)
    stochastic_d: float | None = Field(default=None)
    ichimoku_weekly_tenkan: float | None = Field(default=None)
    ichimoku_weekly_kijun: float | None = Field(default=None)
    ichimoku_weekly_span_a: float | None = Field(default=None)
    ichimoku_weekly_span_b: float | None = Field(default=None)
    ichimoku_weekly_cloud_bias: str | None = Field(default=None)
    ichimoku_weekly_cloud_score: float | None = Field(default=None)
    volume_zscore_20d: float | None = Field(default=None)
    spy_relative_strength_20d: float | None = Field(default=None)
    qqq_relative_strength_20d: float | None = Field(default=None)
    beta_spy_60d: float | None = Field(default=None)
    beta_qqq_60d: float | None = Field(default=None)
    nearest_option_expiry_days: int | None = Field(default=None)
    zero_dte_available: bool | None = Field(default=None)
    zero_dte_put_call_volume_ratio: float | None = Field(default=None)
    zero_dte_atm_straddle_pct: float | None = Field(default=None)
    zero_dte_gamma_pressure: float | None = Field(default=None)
    revenue_growth_yoy: float | None = Field(default=None)
    earnings_growth_yoy: float | None = Field(default=None)
    gross_margin: float | None = Field(default=None)
    operating_margin: float | None = Field(default=None)
    fcf_margin: float | None = Field(default=None)
    debt_to_equity: float | None = Field(default=None)
    current_ratio: float | None = Field(default=None)
    institutional_flow_score: float | None = Field(default=None)
    market_cap: float | None = Field(default=None)
    market_cap_bucket: str | None = Field(default=None)
    sector_code: str | None = Field(default=None)
    has_options: bool | None = Field(default=None)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    ticker: str = Field(default="UNKNOWN")
    current_chunk: str = Field(min_length=1, validation_alias="prompt")
    market_data: MarketData = Field(default_factory=MarketData)
    section_type: SectionType = Field(default=SectionType.UNKNOWN)
    source_type: SourceType = Field(default=SourceType.UNKNOWN)
    chunk_sequence: int = Field(default=0, ge=0)
    request_priority: int = Field(default=5, ge=0, le=10)
    is_final: bool = False
    route_profile: str | None = None
    needs_review: bool = False
    universe_profile: str | None = None
    investment_profile: str | None = None
    canonical_bundle: CanonicalEventBundle | None = None
    source_health: list[CanonicalSourceHealth] = Field(default_factory=list)
    evidence_documents: list[EvidenceDocument] = Field(default_factory=list)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
