"""API models for RAG-backed earnings intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

try:
    from models.request_models import MarketData
except ImportError:  # pragma: no cover
    from .request_models import MarketData


class FactCheckVerdict(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ImpactDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class ExternalEvidencePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    doc_id: str = Field(default_factory=lambda: str(uuid4()))
    ticker: str = "UNKNOWN"
    text: str
    title: str = ""
    published_at: int | datetime | None = None
    source_type: str = "news"
    url: str = ""
    form_type: str = ""
    importance: float = Field(default=0.7, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedEvidencePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    doc_id: str
    title: str = ""
    text: str
    score: float
    published_at: int = 0
    source_type: str = "news"
    url: str = ""
    form_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimFactCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim: str
    verdict: FactCheckVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_ko: str
    evidence: list[RetrievedEvidencePayload] = Field(default_factory=list)


class ClaimDiff(BaseModel):
    model_config = ConfigDict(extra="ignore")

    current_claim: str
    prior_claim: str | None = None
    topic: str = "general"
    direction_change: str = "unchanged"
    contradiction_score: float = Field(default=0.0, ge=0.0, le=1.0)
    severity: str = "low"
    rationale_ko: str
    evidence: list[RetrievedEvidencePayload] = Field(default_factory=list)


class OmissionEvasionAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    directness: float = Field(default=1.0, ge=0.0, le=1.0)
    evasion_score: float = Field(default=0.0, ge=0.0, le=1.0)
    omission_score: float = Field(default=0.0, ge=0.0, le=1.0)
    pivot_detected: bool = False
    missing_topics: list[str] = Field(default_factory=list)
    rationale_ko: str


class ImpactNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    relationship: str
    direction: ImpactDirection
    impact_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale_ko: str
    evidence: list[RetrievedEvidencePayload] = Field(default_factory=list)


class RiskPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    available: bool
    direction: str = "NEUTRAL"
    reference_price: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    stop_pct: float | None = None
    take_profit_1_pct: float | None = None
    take_profit_2_pct: float | None = None
    risk_reward_1: float | None = None
    risk_reward_2: float | None = None
    trailing_stop_pct: float | None = None
    time_stop_days: int | None = None
    invalidation_text: str
    sizing_note_ko: str
    assumptions: list[str] = Field(default_factory=list)


class EarningsIntelligenceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    event_text: str = Field(min_length=1)
    question: str | None = None
    answer: str | None = None
    market_data: MarketData = Field(default_factory=MarketData)
    external_documents: list[ExternalEvidencePayload] = Field(default_factory=list)
    related_tickers: list[str] = Field(default_factory=list)
    direction_hint: str | None = None
    confidence_hint: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int = Field(default=5, ge=1, le=12)


class EarningsIntelligenceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_count: int = 0
    retrieved_evidence: list[RetrievedEvidencePayload] = Field(default_factory=list)
    fact_checks: list[ClaimFactCheck] = Field(default_factory=list)
    claim_diffs: list[ClaimDiff] = Field(default_factory=list)
    omission_evasion: OmissionEvasionAnalysis
    impact_chain: list[ImpactNode] = Field(default_factory=list)
    company_intelligence: dict[str, Any] = Field(default_factory=dict)
    risk_plan: RiskPlan
    summary_ko: str
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "ClaimDiff",
    "ClaimFactCheck",
    "EarningsIntelligenceRequest",
    "EarningsIntelligenceResponse",
    "ExternalEvidencePayload",
    "FactCheckVerdict",
    "ImpactDirection",
    "ImpactNode",
    "OmissionEvasionAnalysis",
    "RetrievedEvidencePayload",
    "RiskPlan",
]
