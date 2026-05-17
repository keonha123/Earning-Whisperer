from __future__ import annotations

from dataclasses import dataclass
import json

from fastapi.testclient import TestClient

from core.gemini_client import GenerationUsage
from main import create_app
from models.equity_report_models import EquityReportRequest
from services.equity_report_service import EquityResearchReportService


@dataclass(slots=True)
class FakeGeminiClient:
    text: str

    async def generate_content_with_metadata(self, *, model: str, contents: str, config: dict):
        assert config["response_mime_type"] == "application/json"
        return GenerationUsage(
            text=self.text,
            prompt_tokens=123,
            output_tokens=456,
            total_tokens=579,
            estimated_cost_usd=0.0123,
        )


class FailingGeminiClient:
    async def generate_content_with_metadata(self, *, model: str, contents: str, config: dict):
        raise RuntimeError("boom")


def _snapshot(_: str) -> dict:
    return {
        "company_name": "NVIDIA Corporation",
        "current_price": 123.45,
        "market_cap": 1_000_000_000,
        "sector": "Technology",
        "trailing_pe": 35.5,
    }


def _structured_json(ticker: str = "NVDA") -> str:
    return json.dumps(
        {
            "rating_box": {
                "ticker": ticker,
                "company_name": "NVIDIA Corporation",
                "current_price": "$123.45",
                "market_cap": "$1.0B",
                "rating": "Hold",
                "conviction": "Medium",
                "base_case_price_target": "$130",
                "bull_case_price_target": "$160",
                "bear_case_price_target": "$90",
                "expected_upside_downside": "+5.3%",
                "key_thesis": ["AI demand remains strong", "Valuation requires execution", "Margin durability is the key debate"],
            },
            "sections": [
                {
                    "id": "business_model",
                    "title": "Business Model Breakdown",
                    "summary": "NVIDIA sells accelerated computing platforms.",
                    "bullets": ["Revenue is product and platform driven."],
                    "tables": [],
                },
                {
                    "id": "valuation_snapshot",
                    "title": "Valuation Snapshot",
                    "summary": "The stock trades at a premium multiple.",
                    "bullets": [],
                    "tables": [
                        {
                            "title": "Valuation",
                            "columns": ["Metric", "Value"],
                            "rows": [["Trailing P/E", "35.5"], ["Current Price", "$123.45"]],
                        }
                    ],
                },
            ],
            "key_catalysts": ["Next earnings report", "Guidance revision"],
            "key_risks": ["Valuation compression", "Gross margin normalization"],
            "scenarios": [
                {"case": "bull", "thesis": "AI capex extends.", "assumptions": ["Revenue beats"], "price_target": "$160", "probability": "25%"},
                {"case": "base", "thesis": "Growth normalizes.", "assumptions": ["Consensus met"], "price_target": "$130", "probability": "50%"},
                {"case": "bear", "thesis": "Multiple compresses.", "assumptions": ["Growth slows"], "price_target": "$90", "probability": "25%"},
            ],
            "final_verdict": "Hold with medium conviction.",
            "analyst_assumptions": ["Numbers should be verified against filings."],
            "data_gaps": [],
        }
    )


def test_equity_report_service_returns_structured_report_markdown_and_usage() -> None:
    service = EquityResearchReportService(
        llm_client=FakeGeminiClient(_structured_json("NVDA")),
        market_data_provider=_snapshot,
    )

    response = TestClient(create_app()).app.state.equity_report_service
    assert response is not None

    import asyncio

    result = asyncio.run(service.generate_report(EquityReportRequest(ticker="nvda", concerns="valuation")))

    assert result.ticker == "NVDA"
    assert result.output_format == "structured"
    assert result.company_name == "NVIDIA Corporation"
    assert result.structured_report.rating_box.rating == "Hold"
    assert result.structured_report.sections[0].id == "business_model"
    assert result.report_markdown.startswith("# NVDA")
    assert "Valuation Snapshot" in result.report_markdown
    assert result.prompt_tokens == 123
    assert result.output_tokens == 456
    assert result.fallback_used is False
    assert result.sources


def test_equity_report_api_aliases_return_structured_payload() -> None:
    app = create_app()
    app.state.equity_report_service = EquityResearchReportService(
        llm_client=FakeGeminiClient(_structured_json("MSFT")),
        market_data_provider=_snapshot,
    )
    client = TestClient(app)

    for path in ["/v1/research/equity-report", "/api/v1/research/equity-report"]:
        response = client.post(path, json={"ticker": "msft", "concerns": "AI exposure"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ticker"] == "MSFT"
        assert payload["output_format"] == "structured"
        assert payload["structured_report"]["rating_box"]["rating"] == "Hold"
        assert "report_markdown" in payload
        assert payload["fallback_used"] is False
        assert payload["data_quality"]["freshness"] == "live_or_recent"


def test_equity_report_still_accepts_markdown_output_format_for_compatibility() -> None:
    service = EquityResearchReportService(
        llm_client=FakeGeminiClient(_structured_json("AAPL")),
        market_data_provider=_snapshot,
    )

    import asyncio

    result = asyncio.run(service.generate_report(EquityReportRequest(ticker="AAPL", output_format="markdown")))

    assert result.output_format == "markdown"
    assert result.structured_report.rating_box.ticker == "AAPL"
    assert result.report_markdown.startswith("# AAPL")


def test_equity_report_falls_back_when_gemini_fails() -> None:
    service = EquityResearchReportService(
        llm_client=FailingGeminiClient(),
        market_data_provider=_snapshot,
    )

    import asyncio

    result = asyncio.run(service.generate_report(EquityReportRequest(ticker="TSLA")))

    assert result.ticker == "TSLA"
    assert result.fallback_used is True
    assert result.structured_report.rating_box.rating == "Hold"
    assert "Hold / Low Conviction" in result.report_markdown
    assert result.data_quality.warnings
