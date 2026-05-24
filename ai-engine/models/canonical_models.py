from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class CanonicalCompany(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str | None = None
    company_name: str | None = None
    sector_code: str | None = None
    market_cap: float | None = None
    market_cap_bucket: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalEarningsEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str | None = None
    fiscal_quarter: str | None = None
    event_time: datetime | None = None
    market_session: str | None = None
    event_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalTranscript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prepared_summary: str | None = None
    qa_summary: str | None = None
    prepared_vs_qa_gap: float | None = None
    qna_sentiment_delta: float | None = None
    key_quotes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalGuidance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    direction: str | None = None
    summary: str | None = None
    revenue_growth_pct: float | None = None
    margin_delta_pct: float | None = None
    capex_delta_pct: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalMarketOverlay(BaseModel):
    model_config = ConfigDict(extra="ignore")

    short_interest_pct: float | None = None
    insider_net_flow: float | None = None
    price_reaction_pct: float | None = None
    volatility_regime: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalAnalystOverlay(BaseModel):
    model_config = ConfigDict(extra="ignore")

    revision_delta_pct: float | None = None
    consensus_surprise_pct: float | None = None
    credibility_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalSourceHealth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    status: SourceHealthStatus = SourceHealthStatus.UNKNOWN
    freshness_seconds: float | None = None
    latency_ms: float | None = None
    error_rate_pct: float | None = None
    last_success_at: datetime | None = None
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalEventBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company: CanonicalCompany | None = None
    earnings_event: CanonicalEarningsEvent | None = None
    transcript: CanonicalTranscript | None = None
    guidance: CanonicalGuidance | None = None
    market_overlay: CanonicalMarketOverlay | None = None
    analyst_overlay: CanonicalAnalystOverlay | None = None
    source_health: list[CanonicalSourceHealth] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CanonicalAnalystOverlay",
    "CanonicalCompany",
    "CanonicalEarningsEvent",
    "CanonicalEventBundle",
    "CanonicalGuidance",
    "CanonicalMarketOverlay",
    "CanonicalSourceHealth",
    "CanonicalTranscript",
    "SourceHealthStatus",
]
