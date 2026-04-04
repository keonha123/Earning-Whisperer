"""Request models for analysis, batch ingest, and research APIs."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    EARNINGS_CALL = "EARNINGS_CALL"
    STT_STREAM = "STT_STREAM"
    PREPARED_REMARKS = "PREPARED_REMARKS"
    Q_AND_A = "Q_AND_A"
    PRESS_RELEASE = "PRESS_RELEASE"
    NEWS = "NEWS"
    FILING = "FILING"
    SOCIAL = "SOCIAL"
    TRANSCRIPT_BATCH = "TRANSCRIPT_BATCH"


class SectionType(str, Enum):
    PREPARED_REMARKS = "PREPARED_REMARKS"
    Q_AND_A = "Q_AND_A"
    OTHER = "OTHER"


class MarketData(BaseModel):
    """Quant, event, and execution inputs used during scoring."""

    # Price and technicals
    prev_close: Optional[float] = Field(None)
    current_price: Optional[float] = Field(None)
    price_change_pct: Optional[float] = Field(None)
    rsi_14: Optional[float] = Field(None, ge=0.0, le=100.0)
    macd_signal: Optional[float] = Field(None)
    bb_position: Optional[float] = Field(None, ge=0.0, le=1.0)
    atr_14: Optional[float] = Field(None, gt=0.0)
    volume_ratio: Optional[float] = Field(None, ge=0.0)
    ma20: Optional[float] = Field(None)
    high_52w: Optional[float] = Field(None)
    relative_strength_20d: Optional[float] = Field(None, ge=-1.0, le=1.0)
    realized_vol_10d: Optional[float] = Field(None, ge=0.0)

    # Market regime
    vix: Optional[float] = Field(None, ge=0.0)

    # Earnings and revisions
    earnings_surprise_pct: Optional[float] = Field(None)
    avg_analyst_est: Optional[float] = Field(None)
    whisper_eps: Optional[float] = Field(None)
    analyst_revision_delta_pct: Optional[float] = Field(None)

    # Pre-market and execution quality
    gap_pct: Optional[float] = Field(None)
    premarket_volume_ratio: Optional[float] = Field(None, ge=0.0)
    bid_ask_spread_bps: Optional[float] = Field(None, ge=0.0)
    liquidity_score: Optional[float] = Field(None, ge=0.0, le=1.0)

    # Options and positioning
    put_call_ratio: Optional[float] = Field(None, ge=0.0)
    current_iv: Optional[float] = Field(None, ge=0.0, le=5.0)
    iv_rank: Optional[float] = Field(None, ge=0.0, le=100.0)
    hours_to_earnings: Optional[float] = Field(None, ge=0.0)
    options_volume_ratio: Optional[float] = Field(None, ge=0.0)
    implied_move_pct: Optional[float] = Field(None, ge=0.0)

    # Short interest
    short_interest_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    days_to_cover: Optional[float] = Field(None, ge=0.0)

    # Misc
    hours_since_news: Optional[float] = Field(None, ge=0.0)
    first_5min_close: Optional[float] = Field(None)
    first_5min_open: Optional[float] = Field(None)

    @field_validator("atr_14")
    @classmethod
    def _atr_positive(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value <= 0:
            raise ValueError("atr_14 must be positive")
        return value

    @field_validator("current_price", "prev_close")
    @classmethod
    def _price_positive(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value <= 0:
            raise ValueError("price values must be positive")
        return value


class AnalyzeRequest(BaseModel):
    """Incoming unit of transcript/event analysis."""

    ticker: str = Field(..., min_length=1, max_length=10)
    text_chunk: str = Field(..., min_length=1)
    sequence: int = Field(..., ge=0)
    timestamp: int = Field(..., gt=0)
    is_final: bool = Field(...)
    market_data: Optional[MarketData] = Field(None)

    # New optional metadata for multi-call / multi-source ingestion
    call_id: Optional[str] = Field(None, description="Unique earnings call identifier.")
    event_id: Optional[str] = Field(None, description="Source event identifier.")
    batch_id: Optional[str] = Field(None, description="Batch ingestion identifier.")
    source_type: Optional[SourceType] = Field(default=SourceType.EARNINGS_CALL)
    section_type: Optional[SectionType] = Field(default=SectionType.OTHER)
    speaker_role: Optional[str] = Field(None)
    speaker_name: Optional[str] = Field(None)
    transcript_language: Optional[str] = Field(default="en")
    request_priority: int = Field(default=5, ge=1, le=10)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("text_chunk")
    @classmethod
    def _validate_text_chunk(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text_chunk must not be empty")
        return stripped

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ticker": "NVDA",
                    "text_chunk": "Our data center revenue grew 409% year-over-year.",
                    "sequence": 12,
                    "timestamp": 1741827000,
                    "is_final": False,
                    "call_id": "NVDA-2026Q1",
                    "event_id": "transcript-0012",
                    "source_type": "Q_AND_A",
                    "section_type": "Q_AND_A",
                    "speaker_role": "CEO",
                    "market_data": {
                        "current_price": 901.20,
                        "prev_close": 879.50,
                        "rsi_14": 62.3,
                        "macd_signal": 0.025,
                        "bb_position": 0.71,
                        "atr_14": 18.5,
                        "volume_ratio": 2.8,
                        "vix": 16.4,
                        "earnings_surprise_pct": 15.2,
                        "bid_ask_spread_bps": 8.5,
                        "liquidity_score": 0.92,
                    },
                }
            ]
        }
    }


class AnalyzeBatchRequest(BaseModel):
    """Batch request for high-throughput transcript ingestion."""

    items: List[AnalyzeRequest] = Field(..., min_length=1)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    batch_label: Optional[str] = Field(None)
