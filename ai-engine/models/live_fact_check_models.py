from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Ticker = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1)]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class LiveFactCheckVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class LiveFactCheckReasonCode(str, Enum):
    SUPPORTED_BY_NEWS = "supported_by_news"
    CONTRADICTED_BY_NEWS = "contradicted_by_news"
    INSUFFICIENT_RELEVANCE = "insufficient_relevance"
    EVIDENCE_NOT_SPECIFIC = "evidence_not_specific"
    RETRIEVAL_FAILED = "retrieval_failed"
    LLM_FAILED = "llm_failed"
    INVALID_LLM_RESPONSE = "invalid_llm_response"


class LiveFactCheckBatchStatus(str, Enum):
    BUFFERING = "BUFFERING"
    COMPLETED = "COMPLETED"
    DISCARDED = "DISCARDED"
    REJECTED = "REJECTED"


class LiveFactCheckSentenceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: Ticker
    sentence: NonEmptyText
    sentence_sequence: int = Field(ge=0)
    sentence_timestamp: int = Field(gt=0)
    is_session_end: bool = False


class LiveFactCheckEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    doc_id: str
    title: str = ""
    snippet: str
    url: str = ""
    source: str = "unknown"
    published_at: int
    relevance_score: float = Field(ge=0.0, le=1.0)


class LiveClaimFactCheckResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_id: str
    sentence_index: int = Field(ge=0, le=2)
    source_text: str
    claim: str
    claim_type: str
    verdict: LiveFactCheckVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    explanation_ko: str
    reason_code: LiveFactCheckReasonCode
    evidence: list[LiveFactCheckEvidence] = Field(default_factory=list)
    retrieved_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)


class LiveFactCheckBatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    status: LiveFactCheckBatchStatus
    buffered_count: int = Field(default=0, ge=0, le=2)
    batch_start_sequence: int | None = None
    batch_end_sequence: int | None = None
    claims: list[LiveClaimFactCheckResult] = Field(default_factory=list)
    excluded_count: int = Field(default=0, ge=0)
    extraction_llm_used: bool = False
    verification_llm_used: bool = False
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "LiveClaimFactCheckResult",
    "LiveFactCheckBatchResponse",
    "LiveFactCheckBatchStatus",
    "LiveFactCheckEvidence",
    "LiveFactCheckReasonCode",
    "LiveFactCheckSentenceRequest",
    "LiveFactCheckVerdict",
]
