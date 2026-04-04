"""Shared signal and analysis models."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class MarketRegime(str, Enum):
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    EXTREME_FEAR = "EXTREME_FEAR"
    NORMAL = "NORMAL"


class CatalystType(str, Enum):
    EARNINGS_BEAT = "EARNINGS_BEAT"
    EARNINGS_MISS = "EARNINGS_MISS"
    GUIDANCE_UP = "GUIDANCE_UP"
    GUIDANCE_DOWN = "GUIDANCE_DOWN"
    GUIDANCE_HOLD = "GUIDANCE_HOLD"
    RESTRUCTURING = "RESTRUCTURING"
    PRODUCT_NEWS = "PRODUCT_NEWS"
    MACRO_COMMENTARY = "MACRO_COMMENTARY"
    REGULATORY_RISK = "REGULATORY_RISK"
    OPERATIONAL_EXEC = "OPERATIONAL_EXEC"


class StrategyName(str, Enum):
    SHORT_SQUEEZE = "SHORT_SQUEEZE"
    GAP_AND_GO = "GAP_AND_GO"
    GAP_FILL = "GAP_FILL"
    NEWS_BREAKOUT = "NEWS_BREAKOUT"
    SECTOR_CONTAGION = "SECTOR_CONTAGION"
    IV_CRUSH = "IV_CRUSH"
    WHISPER_PLAY = "WHISPER_PLAY"
    CONTRARIAN = "CONTRARIAN"
    SENTIMENT_ONLY = "SENTIMENT_ONLY"
    ERROR_FALLBACK = "ERROR_FALLBACK"


class WhisperSignal(str, Enum):
    ABOVE_WHISPER = "ABOVE_WHISPER"
    AT_WHISPER = "AT_WHISPER"
    BELOW_WHISPER = "BELOW_WHISPER"
    UNKNOWN = "UNKNOWN"


class GateLabel(str, Enum):
    G1 = "g1"
    G2 = "g2"
    G3 = "g3"
    G4 = "g4"
    G5 = "g5"


class GeminiAnalysisResult(BaseModel):
    """Structured Gemini output used inside the engine."""

    direction: str = Field(..., description="BULLISH / BEARISH / NEUTRAL")
    magnitude: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = Field(..., description="Short rationale for the call.")
    catalyst_type: str = Field(default="MACRO_COMMENTARY")
    euphemism_count: int = Field(default=0, ge=0)
    euphemisms: Optional[List[str]] = Field(default=None)
    negative_word_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    cot_reasoning: Optional[str] = Field(default=None)
    model_route: Optional[str] = Field(default=None)
    consensus_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    disagreement_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> str:
        normalized = str(value or "NEUTRAL").strip().upper()
        if normalized not in {"BULLISH", "BEARISH", "NEUTRAL"}:
            return "NEUTRAL"
        return normalized

    @field_validator("catalyst_type", mode="before")
    @classmethod
    def _normalize_catalyst(cls, value: object) -> str:
        normalized = str(value or "MACRO_COMMENTARY").strip().upper()
        valid = {member.value for member in CatalystType}
        if normalized not in valid:
            return "MACRO_COMMENTARY"
        return normalized

    @field_validator("magnitude", "confidence", "negative_word_ratio", mode="before")
    @classmethod
    def _coerce_float(cls, value: object) -> float:
        if value in (None, ""):
            return 0.0
        return float(value)

    @field_validator("euphemism_count", mode="before")
    @classmethod
    def _coerce_euphemism_count(cls, value: object) -> int:
        if value in (None, ""):
            return 0
        return max(0, int(value))

    @model_validator(mode="after")
    def _backfill_euphemism_count(self) -> "GeminiAnalysisResult":
        if self.euphemisms:
            self.euphemism_count = max(self.euphemism_count, len(self.euphemisms))
        return self


class TradingSignalV3(BaseModel):
    """Final Redis payload emitted by the AI engine."""

    ticker: str = Field(..., description="Ticker symbol.")
    raw_score: float = Field(..., ge=-1.0, le=1.0, description="Normalized sentiment score.")
    rationale: str = Field(..., description="LLM rationale.")
    text_chunk: str = Field(..., description="Original STT chunk.")
    timestamp: int = Field(..., description="UTC Unix epoch seconds.")

    composite_score: Optional[float] = Field(None, ge=-1.0, le=1.0)
    sue_score: Optional[float] = Field(None, ge=-5.0, le=5.0)
    momentum_score: Optional[float] = Field(None, ge=-1.0, le=1.0)

    trade_approved: Optional[bool] = Field(None)
    primary_strategy: Optional[StrategyName] = Field(None)
    signal_strength: Optional[SignalStrength] = Field(None)
    position_pct: Optional[float] = Field(None, ge=0.0, le=0.25)
    market_regime: Optional[MarketRegime] = Field(None)
    catalyst_type: Optional[CatalystType] = Field(None)

    stop_loss_price: Optional[float] = Field(None)
    take_profit_price: Optional[float] = Field(None)
    stop_loss_pct: Optional[float] = Field(None)
    take_profit_pct: Optional[float] = Field(None)
    profit_factor: Optional[float] = Field(None)
    hold_days_max: Optional[int] = Field(None, ge=1)

    failed_gates: Optional[List[GateLabel]] = Field(None)
    whisper_signal: Optional[WhisperSignal] = Field(None)
    sector_contagion: Optional[bool] = Field(None)
    cot_reasoning: Optional[str] = Field(None)
