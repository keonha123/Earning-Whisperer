"""Models for research, backtesting, and execution-style endpoints."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .request_models import MarketData, SectionType
from .signal_models import StrategyName


class SignalRecordRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    timestamp: int = Field(..., gt=0)
    composite_score: float = Field(..., ge=-1.0, le=1.0)
    raw_score: float = Field(..., ge=-1.0, le=1.0)
    trade_approved: bool
    strategy: str
    actual_return: Optional[float] = Field(None)


class BacktestRequest(BaseModel):
    records: List[SignalRecordRequest] = Field(..., min_length=1)


class StyleRecommendationRequest(BaseModel):
    strategy: StrategyName
    composite_score: float = Field(..., ge=-1.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    trade_approved: bool
    market_data: Optional[MarketData] = Field(None)
    section_type: Optional[SectionType] = Field(default=SectionType.OTHER)

