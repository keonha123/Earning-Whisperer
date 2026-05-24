from __future__ import annotations

import asyncio

from core.analysis_service import AnalysisService
from core.gemini_client import GenerationUsage
from models.request_models import MarketData, SectionType, SourceType


async def _invalid_json_response(**kwargs) -> GenerationUsage:
    return GenerationUsage(
        text="this is not valid json",
        prompt_tokens=120,
        output_tokens=24,
        total_tokens=144,
        estimated_cost_usd=0.0003,
    )


def test_analysis_service_returns_neutral_fallback_on_invalid_llm_json(monkeypatch) -> None:
    service = AnalysisService()
    monkeypatch.setattr("core.analysis_service.gemini_client.generate_content_with_metadata", _invalid_json_response)

    result = asyncio.run(
        service.analyze(
            ticker="NVDA",
            current_chunk="Management said demand trends remain stable.",
            market_data=MarketData(ticker="NVDA", current_price=100.0, volume_ratio=1.5, surprise_pct=2.0),
            section_type=SectionType.GUIDANCE,
            source_type=SourceType.NEWS,
            chunk_sequence=3,
            request_priority=5,
            is_final=False,
            route_profile="economy",
        )
    )

    assert result.direction == "NEUTRAL"
    assert result.confidence == 0.0
    assert result.metadata["llm_error"]["stage"] == "response_parse_or_schema_validation"
    assert result.model_route
    assert result.metadata["signal_data_hub"]["feature_bundle_topic"] == "feature_bundle:nvda"
    assert result.metadata["institutional_edge"]["approval_state"] in {"research_only", "retail_summary_only"}
    assert "no_directional_edge" in result.metadata["institutional_edge"]["blockers"]
