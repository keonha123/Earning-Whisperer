"""Request and response contracts for frontend-ready equity research reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class EquityReportRequest(BaseModel):
    """Ticker-level research report request used by Backend proxy and frontend."""

    ticker: str = Field(..., min_length=1, max_length=16)
    concerns: str | None = Field(default=None, max_length=2000)
    language: Literal["ko", "en"] = "ko"
    output_format: Literal["structured", "markdown"] = "structured"

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = "".join(ch for ch in value.strip().upper() if ch.isalnum() or ch in {".", "-"})
        if not normalized:
            raise ValueError("ticker is required")
        return normalized


class EquityReportDataQuality(BaseModel):
    """Data freshness and graceful-degradation metadata for report rendering."""

    freshness: str = "unknown"
    missing_items: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EquityReportSource(BaseModel):
    """Source item that the frontend can render under the report."""

    name: str
    url: str | None = None
    source_type: str = "data"


class ResearchRatingBox(BaseModel):
    """Top-level card fields for the report hero section."""

    ticker: str
    company_name: str | None = None
    current_price: str | None = None
    market_cap: str | None = None
    rating: Literal["Buy", "Hold", "Avoid"] = "Hold"
    conviction: Literal["Low", "Medium", "High"] = "Low"
    base_case_price_target: str | None = None
    bull_case_price_target: str | None = None
    bear_case_price_target: str | None = None
    expected_upside_downside: str | None = None
    key_thesis: list[str] = Field(default_factory=list)


class ResearchTable(BaseModel):
    """Generic table for frontend rendering without Markdown parsing."""

    title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class ResearchSection(BaseModel):
    """Structured body section for cards, tabs, or section navigation."""

    id: str
    title: str
    summary: str = ""
    bullets: list[str] = Field(default_factory=list)
    tables: list[ResearchTable] = Field(default_factory=list)


class ResearchScenario(BaseModel):
    """Bull/base/bear case scenario block."""

    case: Literal["bull", "base", "bear"]
    thesis: str = ""
    assumptions: list[str] = Field(default_factory=list)
    price_target: str | None = None
    probability: str | None = None


class StructuredEquityReport(BaseModel):
    """Canonical frontend contract for equity research output."""

    rating_box: ResearchRatingBox
    sections: list[ResearchSection] = Field(default_factory=list)
    key_catalysts: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    scenarios: list[ResearchScenario] = Field(default_factory=list)
    final_verdict: str = ""
    analyst_assumptions: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class EquityReportResponse(BaseModel):
    """Equity report response optimized for robust frontend rendering."""

    ticker: str
    company_name: str | None = None
    generated_at: datetime
    language: Literal["ko", "en"] = "ko"
    output_format: Literal["structured", "markdown"] = "structured"
    structured_report: StructuredEquityReport
    report_markdown: str
    sources: list[EquityReportSource] = Field(default_factory=list)
    data_quality: EquityReportDataQuality = Field(default_factory=EquityReportDataQuality)
    market_snapshot: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    model_route: str = "review"
    prompt_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    fallback_used: bool = False


__all__ = [
    "EquityReportDataQuality",
    "EquityReportRequest",
    "EquityReportResponse",
    "EquityReportSource",
    "ResearchRatingBox",
    "ResearchScenario",
    "ResearchSection",
    "ResearchTable",
    "StructuredEquityReport",
]
