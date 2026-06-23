"""Backward-compatible request and signal contracts for the original GitHub stack."""

from __future__ import annotations

from time import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class LegacyAnalyzeRequest(BaseModel):
    """Input shape used by the original data-pipeline -> AI-engine contract."""

    model_config = ConfigDict(extra="ignore")

    ticker: str = Field(min_length=1)
    text_chunk: str = Field(min_length=1)
    sequence: int = Field(default=0, ge=0)
    timestamp: int = Field(default_factory=lambda: int(time()))
    is_final: bool = False

    # Additive fields let newer callers pass richer context without breaking
    # the original five-field payload.
    market_data: dict[str, Any] = Field(default_factory=dict)
    section_type: str | None = None
    source_type: str | None = None
    request_priority: int = Field(default=5, ge=0, le=10)
    route_profile: str | None = None
    needs_review: bool = False
    universe_profile: str | None = None
    investment_profile: str | None = None


class LegacySignalMessage(BaseModel):
    """Redis message shape consumed by the original Spring backend."""

    model_config = ConfigDict(extra="ignore")

    ticker: str
    raw_score: float
    rationale: str
    text_chunk: str
    timestamp: int
    is_session_end: bool = False

    @computed_field(return_type=float)
    @property
    def ai_score(self) -> float:
        """Signed score alias required by the Spring backend contract."""
        return self.raw_score

    # Optional v9 enrichments. Existing Java consumers can ignore them.
    action: str | None = None
    confidence: float | None = None
    strategy: str | None = None
    hold_days: int | None = None
    model_route: str | None = None
    execution_allowed: bool | None = None
    blocked_reason_ko: str | None = None
    signal_brief: dict[str, Any] | None = None
    engine_event_id: str | None = None
    investment_profile: str | None = None
    investment_profile_label_ko: str | None = None
    universe_profile: str | None = None
    risk_style: str | None = None
    redis_output_profile: str | None = None
    strategy_recommendation: dict[str, Any] | None = None
    schema_version: str = "2026-05-13.legacy-ai-signal-v1"


class LegacyAnalyzeResponse(LegacySignalMessage):
    """HTTP response returned by the compatibility endpoint."""

    redis_published: bool = False
    enriched_published: bool = False
    profile_published: bool = False
    profile_channel: str | None = None
    retry_queued: int = 0
    publish_error: str | None = None
    engine_envelope: dict[str, Any] | None = None


class LegacyPublishResult(BaseModel):
    """Result of publishing the legacy and enriched Redis messages."""

    legacy_published: bool = False
    enriched_published: bool = False
    profile_published: bool = False
    profile_channel: str | None = None
    retry_queued: int = 0
    error: str | None = None


__all__ = [
    "LegacyAnalyzeRequest",
    "LegacyAnalyzeResponse",
    "LegacyPublishResult",
    "LegacySignalMessage",
]
