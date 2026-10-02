from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TranscriptSpeakerTurn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speaker: str = ""
    text: str
    section: str | None = None


class EarningsTranscriptIngestItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    provider: str = "investing"
    provider_id: str
    ticker: str
    title: str
    published_at: datetime | int | float | None = None
    fiscal_quarter: str | None = None
    content: str = Field(min_length=1)
    speaker_turns: list[TranscriptSpeakerTurn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider", "provider_id", "ticker", "title")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("ticker")
    @classmethod
    def _upper_ticker(cls, value: str) -> str:
        return value.upper()


class EarningsTranscriptIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[EarningsTranscriptIngestItem] = Field(default_factory=list)


class EarningsTranscriptIngestResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    accepted_count: int = 0
    skipped_count: int = 0
    document_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CollectorNewsIngestItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    provider: str = "finnhub"
    provider_id: str
    ticker: str
    headline: str
    summary: str = ""
    content: str = ""
    url: str = ""
    source: str = ""
    published_at: datetime | int | float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider", "provider_id", "ticker", "headline")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("ticker")
    @classmethod
    def _upper_ticker(cls, value: str) -> str:
        return value.upper()


class CollectorNewsIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[CollectorNewsIngestItem] = Field(default_factory=list)


class CollectorNewsIngestResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    accepted_count: int = 0
    skipped_count: int = 0
    document_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "CollectorNewsIngestItem",
    "CollectorNewsIngestRequest",
    "CollectorNewsIngestResponse",
    "EarningsTranscriptIngestItem",
    "EarningsTranscriptIngestRequest",
    "EarningsTranscriptIngestResponse",
    "TranscriptSpeakerTurn",
]
