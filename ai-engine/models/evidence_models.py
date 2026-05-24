from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceBackend(str, Enum):
    PGVECTOR = "PGVECTOR"
    FAISS = "FAISS"
    QDRANT = "QDRANT"
    LOCAL_SPARSE = "LOCAL_SPARSE"


class EvidenceSourceType(str, Enum):
    EARNINGS_CALL = "EARNINGS_CALL"
    FILING = "FILING"
    EARNINGS_RELEASE = "EARNINGS_RELEASE"
    PRESENTATION = "PRESENTATION"
    NEWS = "NEWS"
    MARKET_DATA = "MARKET_DATA"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    HISTORICAL_GUIDANCE = "HISTORICAL_GUIDANCE"
    ANALYST_NOTE = "ANALYST_NOTE"
    OTHER = "OTHER"


class FactCheckStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"


class ImpactDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    MIXED = "MIXED"
    NEUTRAL = "NEUTRAL"


class EvidenceDocument(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    document_id: str = ""
    ticker: str | None = None
    source_type: EvidenceSourceType = EvidenceSourceType.OTHER
    source: str = "unknown"
    title: str | None = None
    published_at: datetime | date | None = None
    source_url: str | None = None
    content: str = ""
    reliability_score: float = Field(default=0.6, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_id: str
    ticker: str | None = None
    source_type: EvidenceSourceType
    source: str
    title: str | None = None
    published_at: str | None = None
    source_url: str | None = None
    snippet: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    reliability_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    source_types: list[EvidenceSourceType] = Field(default_factory=list)
    documents: list[EvidenceDocument] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    query: str
    backend: EvidenceBackend
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    coverage_score: float = Field(ge=0.0, le=1.0)
    confidence_adjustment: float = Field(ge=-1.0, le=1.0)
    evidence_context: str = ""
    missing_evidence: bool = False
    warnings: list[str] = Field(default_factory=list)


class FactCheckRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    claim: str
    top_k: int = Field(default=5, ge=1, le=20)
    documents: list[EvidenceDocument] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FactCheckResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    claim: str
    fact_check: FactCheckStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    reason: str


class HistoricalClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_id: str = ""
    ticker: str | None = None
    topic: str = "general"
    claim: str
    stated_at: datetime | date | None = None
    source: str = "unknown"
    source_type: EvidenceSourceType = EvidenceSourceType.HISTORICAL_GUIDANCE
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimDiffRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    current_claims: list[str] = Field(default_factory=list)
    current_text: str | None = None
    historical_claims: list[HistoricalClaim] = Field(default_factory=list)
    documents: list[EvidenceDocument] = Field(default_factory=list)


class ClaimDiffItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str
    prior_claim: str | None = None
    current_claim: str
    change_type: str
    risk_score: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceCitation] = Field(default_factory=list)


class ClaimDiffResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    items: list[ClaimDiffItem] = Field(default_factory=list)
    max_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)


class OmissionAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str | None = None
    question: str
    answer: str
    required_slots: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OmissionAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str | None = None
    question_topic: str
    required_slots: list[str]
    answered_slots: list[str]
    omitted_slots: list[str]
    omission_score: float = Field(ge=0.0, le=1.0)
    evasion_score: float = Field(ge=0.0, le=1.0)


class ImpactRelationship(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    relationship: str
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    beta: float | None = None
    etf_weight_pct: float | None = None
    reason: str | None = None


class ImpactChainRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_ticker: str
    source_direction: ImpactDirection = ImpactDirection.NEUTRAL
    catalyst: str | None = None
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    relationships: list[ImpactRelationship] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=30)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImpactChainItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    relationship: str
    impact_direction: ImpactDirection
    impact_score: float = Field(ge=0.0, le=1.0)
    reason_ko: str
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImpactChainResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_ticker: str
    impacted: list[ImpactChainItem] = Field(default_factory=list)
    graph_version: str = "2026-05-24.static-impact-graph.v1"


class TradeExitPlanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    market_data: dict[str, Any] = Field(default_factory=dict)
    strategy: str = "SENTIMENT_ONLY"
    direction: str = "LONG"
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    hold_days: int = Field(default=1, ge=1, le=30)
    risk_flags: list[str] = Field(default_factory=list)
    mfe_mae_profile: dict[str, Any] = Field(default_factory=dict)


class TradeExitPlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    available: bool
    entry_plan: str | None = None
    stop_loss: dict[str, Any] = Field(default_factory=dict)
    take_profit: dict[str, Any] = Field(default_factory=dict)
    time_stop_days: int | None = None
    trailing_stop: dict[str, Any] = Field(default_factory=dict)
    position_scale: float | None = None
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "ClaimDiffItem",
    "ClaimDiffRequest",
    "ClaimDiffResponse",
    "EvidenceBackend",
    "EvidenceCitation",
    "EvidenceDocument",
    "EvidenceRetrievalRequest",
    "EvidenceRetrievalResult",
    "EvidenceSourceType",
    "FactCheckRequest",
    "FactCheckResponse",
    "FactCheckStatus",
    "HistoricalClaim",
    "ImpactChainItem",
    "ImpactChainRequest",
    "ImpactChainResponse",
    "ImpactDirection",
    "ImpactRelationship",
    "OmissionAnalysisRequest",
    "OmissionAnalysisResponse",
    "TradeExitPlanRequest",
    "TradeExitPlanResponse",
]
