"""Models for external-RAG decisions and evidence records."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


AllowedSourceType = Literal["news", "filing", "press_release", "ir"]


class ExternalRagDecision(BaseModel):
    """Structured LLM decision for whether external RAG is needed."""

    use_external_rag: bool = Field(default=False)
    decision_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_reason: str = Field(default="")
    external_query: str = Field(default="")
    preferred_sources: list[AllowedSourceType] = Field(default_factory=list)
    lookback_days: int = Field(default=7, ge=1)

    @field_validator("retrieval_reason", "external_query", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("preferred_sources", mode="before")
    @classmethod
    def _normalize_sources(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]

        allowed = {"news", "filing", "press_release", "ir"}
        normalized: list[str] = []
        for item in value:
            source = str(item or "").strip().lower()
            if source in allowed and source not in normalized:
                normalized.append(source)
        return normalized


class ExternalQueryRewrite(BaseModel):
    """Structured LLM query-rewrite result."""

    external_query: str = Field(default="")
    rewrite_reason: Optional[str] = Field(default="")

    @field_validator("external_query", "rewrite_reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()
