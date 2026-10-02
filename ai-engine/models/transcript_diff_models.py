from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

try:
    from models.request_models import SourceType
except ImportError:  # pragma: no cover
    from .request_models import SourceType


class TranscriptDiffRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    ticker: str = Field(min_length=1)
    current_chunk: str = Field(min_length=1, validation_alias="text_chunk")
    source_type: SourceType = Field(default=SourceType.EARNINGS_CALL)
    request_metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptDiffResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    available: bool
    ticker: str
    previous_document: dict[str, Any] | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = ["TranscriptDiffRequest", "TranscriptDiffResponse"]
