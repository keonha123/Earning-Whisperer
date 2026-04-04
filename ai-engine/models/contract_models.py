"""Cross-service contract models used by the broader EarningWhisperer system."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class BackendRedisSignal(BaseModel):
    """Contract 2: AI Engine -> Backend Redis payload."""

    ticker: str = Field(..., min_length=1, max_length=10)
    raw_score: float = Field(..., ge=-1.0, le=1.0)
    rationale: str = Field(..., min_length=1)
    text_chunk: str = Field(..., min_length=1)
    timestamp: int = Field(..., gt=0)
    is_session_end: bool = Field(default=False)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

