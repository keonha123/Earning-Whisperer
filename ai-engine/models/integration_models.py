"""Models used to integrate collectors, web live-room views, and desktop callbacks."""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .request_models import AnalyzeRequest, MarketData, SectionType, SourceType


class MarketSession(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    POST_MARKET = "POST_MARKET"
    UNKNOWN = "UNKNOWN"


class CollectorSource(str, Enum):
    COLLECTOR = "COLLECTOR"
    ANALYSIS_TEAM = "ANALYSIS_TEAM"
    BACKEND = "BACKEND"
    DESKTOP = "DESKTOP"
    MANUAL = "MANUAL"


class EarningsScheduleItem(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    scheduled_at: int = Field(..., gt=0)
    call_id: Optional[str] = Field(None)
    event_id: Optional[str] = Field(None)
    fiscal_year: Optional[int] = Field(None, ge=2000, le=2100)
    fiscal_quarter: Optional[str] = Field(None)
    company_name: Optional[str] = Field(None)
    source: CollectorSource = Field(default=CollectorSource.COLLECTOR)
    market_session: MarketSession = Field(default=MarketSession.UNKNOWN)
    webcast_url: Optional[str] = Field(None)
    has_transcript: bool = Field(default=False)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()


class EarningsScheduleBatchRequest(BaseModel):
    items: List[EarningsScheduleItem] = Field(..., min_length=1)


class CompanyUniverseItem(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    company_name: Optional[str] = Field(None)
    sector: Optional[str] = Field(None)
    industry: Optional[str] = Field(None)
    exchange: Optional[str] = Field(None)
    country: Optional[str] = Field(None)
    currency: Optional[str] = Field(None)
    is_watchlist: bool = Field(default=True)
    tags: List[str] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()


class CompanyUniverseBatchRequest(BaseModel):
    items: List[CompanyUniverseItem] = Field(..., min_length=1)


class IndicatorSnapshotItem(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    timestamp: int = Field(..., gt=0)
    market_data: MarketData
    source: CollectorSource = Field(default=CollectorSource.COLLECTOR)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()


class IndicatorSnapshotBatchRequest(BaseModel):
    items: List[IndicatorSnapshotItem] = Field(..., min_length=1)


class MarketContextSnapshot(BaseModel):
    timestamp: int = Field(..., gt=0)
    vix: Optional[float] = Field(None, ge=0.0)
    put_call_ratio: Optional[float] = Field(None, ge=0.0)
    realized_vol_regime: Optional[str] = Field(None)
    liquidity_regime: Optional[str] = Field(None)
    breadth_adv_dec_ratio: Optional[float] = Field(None)
    notes: Optional[str] = Field(None)
    sector_heatmap: Optional[Dict[str, float]] = Field(default=None)


class TranscriptChunkIngestRequest(AnalyzeRequest):
    """Collector-facing alias for analyze requests."""

    collector_trace_id: Optional[str] = Field(None)
    source_type: Optional[SourceType] = Field(default=SourceType.EARNINGS_CALL)
    section_type: Optional[SectionType] = Field(default=SectionType.OTHER)


class DesktopExecutionFeedbackRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    executed_at: int = Field(..., gt=0)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(..., gt=0.0)
    avg_fill_price: float = Field(..., gt=0.0)
    is_paper: bool = Field(default=True)
    broker_name: Optional[str] = Field(None)
    order_id: Optional[str] = Field(None)
    client_order_id: Optional[str] = Field(None)
    account_id_hash: Optional[str] = Field(None)
    strategy: Optional[str] = Field(None)
    call_id: Optional[str] = Field(None)
    event_id: Optional[str] = Field(None)
    signal_timestamp: Optional[int] = Field(None, gt=0)
    realized_pnl_pct: Optional[float] = Field(None)
    notes: Optional[str] = Field(None)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()


class LiveRoomSignalView(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    timestamp: int
    updated_at: int
    call_id: Optional[str] = None
    event_id: Optional[str] = None
    source_type: Optional[str] = None
    section_type: Optional[str] = None
    speaker_role: Optional[str] = None
    speaker_name: Optional[str] = None
    direction: str
    raw_score: float
    composite_score: Optional[float] = None
    signal_strength: Optional[str] = None
    catalyst_type: Optional[str] = None
    market_regime: Optional[str] = None
    rationale: str
    text_excerpt: str
    analysis_only: bool = True
    contains_trade_fields: bool = False

