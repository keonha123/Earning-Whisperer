from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StrategyName(str, Enum):
    MOMENTUM_CARRY = "MOMENTUM_CARRY"
    PEAD = "PEAD"
    REVERSAL_CATALYST = "REVERSAL_CATALYST"
    IV_CRUSH_DECAY = "IV_CRUSH_DECAY"
    GAP_AND_GO = "GAP_AND_GO"
    GAP_FILL = "GAP_FILL"
    WHISPER_PLAY = "WHISPER_PLAY"
    SHORT_SQUEEZE = "SHORT_SQUEEZE"
    NEWS_BREAKOUT = "NEWS_BREAKOUT"
    SECTOR_CONTAGION = "SECTOR_CONTAGION"
    SENTIMENT_ONLY = "SENTIMENT_ONLY"
    CONTRARIAN = "CONTRARIAN"
    ERROR_FALLBACK = "ERROR_FALLBACK"


class GeminiAnalysisResult(BaseModel):
    direction: str
    magnitude: float
    confidence: float
    rationale: str
    catalyst_type: str
    euphemism_count: int = 0
    negative_word_ratio: float = 0.0
    cot_reasoning: str | None = None
    model_route: str = "fallback"
    strategy: str | None = None
    route_profile: str = "economy"
    review_triggered: bool = False
    hold_days: int = 1
    risk_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    disagreement_score: float | None = None
    review_reason: str | None = None
    source_type: str | None = None
    chunk_sequence: int | None = None
    signal_explanation: str | None = None
    hold_days_reason: str | None = None


@dataclass(slots=True)
class StrategyDecision:
    strategy: StrategyName
    score: float
    hold_days: int
    rationale: str
    risk_flags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SignalResult:
    direction: str
    magnitude: float
    confidence: float
    rationale: str
    catalyst_type: str
    euphemism_count: int = 0
    negative_word_ratio: float = 0.0
    cot_reasoning: str | None = None
    model_route: str = "fallback"
    strategy: StrategyName = StrategyName.SENTIMENT_ONLY
    route_profile: str = "economy"
    review_triggered: bool = False
    hold_days: int = 1
    risk_flags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
