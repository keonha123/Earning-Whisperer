"""Persistent evidence ingestion and company-intelligence API models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

try:
    from models.evidence_models import EvidenceDocument, ImpactRelationship
except ImportError:  # pragma: no cover
    from .evidence_models import EvidenceDocument, ImpactRelationship


class EvidenceIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    documents: list[EvidenceDocument] = Field(default_factory=list)
    persist: bool = True


class EvidenceIngestionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    accepted: int = 0
    persisted: int = 0
    vector_upserted: int = 0
    document_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceSyncRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticker: str
    include_sec_filings: bool = True
    include_news: bool = True
    ir_urls: list[str] = Field(default_factory=list)
    filing_forms: list[str] = Field(default_factory=lambda: ["10-K", "10-Q", "8-K"])
    max_filings: int = Field(default=8, ge=0, le=50)
    max_news: int = Field(default=12, ge=0, le=50)


class EvidenceSyncResponse(EvidenceIngestionResponse):
    ticker: str
    sources_attempted: list[str] = Field(default_factory=list)
    source_errors: dict[str, str] = Field(default_factory=dict)


class TranscriptIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticker: str
    title: str = "Earnings call transcript"
    text: str | None = None
    pdf_base64: str | None = None
    published_at: datetime | date | None = None
    source_url: str | None = None
    reliability_score: float = Field(default=0.88, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpeakerMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")
    speaker_id: str
    ticker: str
    name: str
    role: str = "unknown"
    is_executive: bool = False
    first_seen_at: datetime | date | None = None
    last_seen_at: datetime | date | None = None
    source_document_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutiveProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    executive_id: str
    ticker: str
    name: str
    current_role: str
    is_ceo: bool = False
    career_history: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    leadership_traits: list[str] = Field(default_factory=list)
    communication_traits: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    as_of_date: date | None = None
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImpactRelationshipRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_ticker: str
    target_ticker: str
    relationship: str
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    beta: float | None = None
    etf_weight_pct: float | None = None
    direction_multiplier: float = Field(default=1.0, ge=-1.0, le=1.0)
    reason_ko: str = ""
    source_document_ids: list[str] = Field(default_factory=list)
    valid_from: date | None = None
    valid_to: date | None = None
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_impact_relationship(self) -> ImpactRelationship:
        return ImpactRelationship(
            ticker=self.target_ticker.upper(),
            relationship=self.relationship,
            strength=self.strength,
            beta=self.beta,
            etf_weight_pct=self.etf_weight_pct,
            reason=self.reason_ko,
        )


class CompanyIntelligenceUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticker: str
    relationships: list[ImpactRelationshipRecord] = Field(default_factory=list)
    executives: list[ExecutiveProfile] = Field(default_factory=list)
    speakers: list[SpeakerMetadata] = Field(default_factory=list)


class CompanyIntelligenceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticker: str
    relationships: list[ImpactRelationshipRecord] = Field(default_factory=list)
    executives: list[ExecutiveProfile] = Field(default_factory=list)
    speakers: list[SpeakerMetadata] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    persistence_backend: str = "json"


class TranscriptIngestResponse(EvidenceIngestionResponse):
    ticker: str
    title: str
    page_count: int = 0
    character_count: int = 0
    chunk_count: int = 0
    speakers: list[SpeakerMetadata] = Field(default_factory=list)


class RedisRetryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    attempted: int = 0
    published: int = 0
    remaining: int = 0
    errors: list[str] = Field(default_factory=list)


__all__ = [
    "CompanyIntelligenceResponse",
    "CompanyIntelligenceUpsertRequest",
    "EvidenceIngestionRequest",
    "EvidenceIngestionResponse",
    "EvidenceSyncRequest",
    "EvidenceSyncResponse",
    "ExecutiveProfile",
    "ImpactRelationshipRecord",
    "RedisRetryResponse",
    "SpeakerMetadata",
    "TranscriptIngestRequest",
    "TranscriptIngestResponse",
]
