"""Typed contracts for persistent live earnings-call sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

try:
    from models.evidence_models import ClaimDiffItem, EvidenceCitation, EvidenceDocument, FactCheckStatus, ImpactChainItem, OmissionAnalysisResponse, TradeExitPlanResponse
    from models.intelligence_models import ExecutiveProfile, SpeakerMetadata
    from models.request_models import MarketData, SectionType
except ImportError:  # pragma: no cover
    from .evidence_models import ClaimDiffItem, EvidenceCitation, EvidenceDocument, FactCheckStatus, ImpactChainItem, OmissionAnalysisResponse, TradeExitPlanResponse
    from .intelligence_models import ExecutiveProfile, SpeakerMetadata
    from .request_models import MarketData, SectionType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExecutionMode(str, Enum):
    MANUAL = "MANUAL"
    SEMI_AUTO = "SEMI_AUTO"
    AUTO_PILOT = "AUTO_PILOT"

    @classmethod
    def _missing_(cls, value: object):
        normalized = str(value or "").strip().upper().replace("-", "_")
        aliases = {
            "ONE_CLICK": cls.SEMI_AUTO,
            "1_CLICK": cls.SEMI_AUTO,
            "AUTO": cls.AUTO_PILOT,
        }
        return aliases.get(normalized)


class FinalSignalAction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class RecommendedOrderTiming(str, Enum):
    PREMARKET = "PREMARKET"
    AT_OPEN = "AT_OPEN"
    REGULAR_SESSION = "REGULAR_SESSION"
    AFTER_HOURS = "AFTER_HOURS"
    WAIT_FOR_CONFIRMATION = "WAIT_FOR_CONFIRMATION"


class LiveSessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str = Field(min_length=1, max_length=32)
    call_title: str = "Live earnings call"
    fiscal_period: str | None = None
    call_started_at: datetime = Field(default_factory=utc_now)
    expected_fact_count: int = Field(default=6, ge=1, le=100)
    market_data: MarketData = Field(default_factory=MarketData)
    investment_profile: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.MANUAL
    requested_quantity: int | None = Field(default=None, ge=1)
    related_tickers: list[str] = Field(default_factory=list)
    publish_final_signal: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class LiveTranscriptChunkRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1)
    sequence: int | None = Field(default=None, ge=0)
    occurred_at: datetime = Field(default_factory=utc_now)
    speaker_name: str | None = None
    speaker_role: str | None = None
    question: str | None = None
    section_type: SectionType = SectionType.UNKNOWN
    market_data: MarketData | None = None
    evidence_documents: list[EvidenceDocument] = Field(default_factory=list)
    request_priority: int = Field(default=7, ge=0, le=10)
    route_profile: str | None = None
    is_final: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class FactCheckProgress(BaseModel):
    processed: int = 0
    expected: int = 6
    supported: int = 0
    contradicted: int = 0
    unverified: int = 0


class LiveFactCheckItem(BaseModel):
    claim_id: str
    claim: str
    fact_check: FactCheckStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    sequence: int
    speaker_name: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)
    evidence: list[EvidenceCitation] = Field(default_factory=list)


class LiveTranscriptTimelineItem(BaseModel):
    sequence: int
    occurred_at: datetime
    speaker_name: str | None = None
    speaker_role: str | None = None
    text: str
    ai_score: float = Field(ge=-1.0, le=1.0)
    direction: str
    confidence: float = Field(ge=0.0, le=1.0)
    action: str = "HOLD"
    fact_check_ids: list[str] = Field(default_factory=list)
    engine_event_id: str | None = None


class LiveSpeakerProfile(BaseModel):
    speaker_id: str
    ticker: str
    name: str
    role: str = "unknown"
    is_executive: bool = False
    observed_chunks: int = 0
    observed_traits: list[str] = Field(default_factory=list)
    guidance_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    session_fact_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    achievements: list[str] = Field(default_factory=list)
    career_history: list[str] = Field(default_factory=list)
    communication_traits: list[str] = Field(default_factory=list)
    statement_history: list[str] = Field(default_factory=list)
    source_profile: SpeakerMetadata | None = None
    executive_profile: ExecutiveProfile | None = None


class EarningsScorecard(BaseModel):
    growth: float = Field(default=50.0, ge=0.0, le=100.0)
    profitability: float = Field(default=50.0, ge=0.0, le=100.0)
    risk_control: float = Field(default=50.0, ge=0.0, le=100.0)
    management_confidence: float = Field(default=50.0, ge=0.0, le=100.0)
    guidance_reliability: float = Field(default=50.0, ge=0.0, le=100.0)
    evidence_quality: float = Field(default=0.0, ge=0.0, le=100.0)
    overall: float = Field(default=50.0, ge=0.0, le=100.0)


class LiveExecutionPolicy(BaseModel):
    mode: ExecutionMode = ExecutionMode.MANUAL
    advisory_only: bool = True
    broker_execution: str = "not_called"
    signal_persisted: bool = True
    requires_user_confirmation: bool = True
    automation_eligible: bool = False
    recommended_order_timing: RecommendedOrderTiming = RecommendedOrderTiming.WAIT_FOR_CONFIRMATION
    rationale_ko: str = "AI 엔진은 주문 초안만 생성하며 실제 주문은 trading-terminal의 확인과 정책을 따릅니다."


class RedisDeliveryState(BaseModel):
    attempted: bool = False
    legacy_published: bool = False
    enriched_published: bool = False
    profile_published: bool = False
    profile_channel: str | None = None
    retry_queued: int = 0
    error: str | None = None


class LiveFinalSignal(BaseModel):
    signal_id: str
    action: FinalSignalAction = FinalSignalAction.HOLD
    direction: str = "NEUTRAL"
    signed_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    ai_score: float = Field(default=50.0, ge=0.0, le=100.0)
    rationale_ko: str = "분석 진행 중입니다."
    execution_allowed: bool = False
    strategy: str = "SENTIMENT_ONLY"
    hold_days: int = 1
    risk_flags: list[str] = Field(default_factory=list)
    order_draft: dict[str, Any] = Field(default_factory=dict)


class LiveEarningsSessionState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "2026-06-20.live-earnings-session-v1"
    session_id: str
    ticker: str
    call_title: str
    fiscal_period: str | None = None
    status: LiveSessionStatus = LiveSessionStatus.ACTIVE
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    expected_fact_count: int = 6
    market_data: MarketData = Field(default_factory=MarketData)
    investment_profile: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.MANUAL
    requested_quantity: int | None = None
    related_tickers: list[str] = Field(default_factory=list)
    publish_final_signal: bool = True
    timeline: list[LiveTranscriptTimelineItem] = Field(default_factory=list)
    fact_checks: list[LiveFactCheckItem] = Field(default_factory=list)
    fact_check_progress: FactCheckProgress = Field(default_factory=FactCheckProgress)
    claim_diffs: list[ClaimDiffItem] = Field(default_factory=list)
    omission_events: list[OmissionAnalysisResponse] = Field(default_factory=list)
    speakers: list[LiveSpeakerProfile] = Field(default_factory=list)
    scorecard: EarningsScorecard = Field(default_factory=EarningsScorecard)
    latest_signal_brief: dict[str, Any] = Field(default_factory=dict)
    latest_engine_envelope: dict[str, Any] = Field(default_factory=dict)
    final_signal: LiveFinalSignal | None = None
    execution_policy: LiveExecutionPolicy = Field(default_factory=LiveExecutionPolicy)
    impact_chain: list[ImpactChainItem] = Field(default_factory=list)
    risk_plan: TradeExitPlanResponse | None = None
    redis_delivery: RedisDeliveryState = Field(default_factory=RedisDeliveryState)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LiveSessionSummary(BaseModel):
    session_id: str
    ticker: str
    call_title: str
    fiscal_period: str | None = None
    status: LiveSessionStatus
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    chunk_count: int = 0
    fact_checks_processed: int = 0
    final_action: FinalSignalAction | None = None
    ai_score: float | None = None


class LiveSessionListResponse(BaseModel):
    sessions: list[LiveSessionSummary] = Field(default_factory=list)


__all__ = [
    "EarningsScorecard",
    "ExecutionMode",
    "FactCheckProgress",
    "FinalSignalAction",
    "LiveEarningsSessionState",
    "LiveExecutionPolicy",
    "LiveFactCheckItem",
    "LiveFinalSignal",
    "LiveSessionListResponse",
    "LiveSessionStartRequest",
    "LiveSessionStatus",
    "LiveSessionSummary",
    "LiveSpeakerProfile",
    "LiveTranscriptChunkRequest",
    "LiveTranscriptTimelineItem",
    "RecommendedOrderTiming",
    "RedisDeliveryState",
    "utc_now",
]
