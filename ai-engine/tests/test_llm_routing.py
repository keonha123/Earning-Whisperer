from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from ..config import get_settings
from ..core.analysis_service import AnalysisService
from ..core.context_manager import ChunkRecord
from ..core.gemini_client import gemini_client
from ..core.llm_consistency import should_request_review
from ..core.llm_router import decide_route
from ..core.phase1_scorer import Phase1ScoreResult
from ..core.prompt_builder import build_prompt
from ..main import create_app
from ..models.request_models import MarketData, SectionType
from ..models.signal_models import GeminiAnalysisResult


def test_decide_route_prefers_economy_for_basic_chunk():
    decision = decide_route(
        current_chunk="Revenue was broadly in line with expectations.",
        context_chunks=[],
        market_data=MarketData(current_price=100.0, volume_ratio=1.1, vix=18.0),
        section_type=SectionType.OTHER,
        request_priority=5,
        is_final=False,
        phase1_raw_score=0.10,
    )

    assert decision.route_profile == "economy"
    assert decision.context_policy == "delta"
    assert decision.primary_model == "gemini-3-flash-preview"


def test_decide_route_prefers_standard_for_qa_chunk():
    decision = decide_route(
        current_chunk="We are raising the full-year outlook and demand remains strong.",
        context_chunks=[],
        market_data=MarketData(current_price=100.0, volume_ratio=1.1, vix=18.0),
        section_type=SectionType.Q_AND_A,
        request_priority=5,
        is_final=False,
        phase1_raw_score=0.10,
    )

    assert decision.route_profile == "standard"
    assert decision.context_policy == "rolling"


def test_economy_prompt_is_shorter_than_standard_prompt_for_same_inputs():
    context = [
        ChunkRecord(sequence=1, text_chunk="We saw record data center demand.", timestamp=1),
    ]
    market_data = MarketData(
        current_price=905.0,
        price_change_pct=2.1,
        volume_ratio=3.0,
        vix=16.0,
        earnings_surprise_pct=11.0,
        gap_pct=3.2,
        bid_ask_spread_bps=8.0,
        liquidity_score=0.92,
        macd_signal=0.02,
        rsi_14=61.0,
    )

    economy_prompt = build_prompt(
        ticker="NVDA",
        current_chunk="We saw record data center demand and improved profitability.",
        context_chunks=context,
        market_data=market_data,
        prompt_profile="economy",
        context_policy="delta",
        phase1_score=0.62,
    )
    standard_prompt = build_prompt(
        ticker="NVDA",
        current_chunk="We saw record data center demand and improved profitability.",
        context_chunks=context,
        market_data=market_data,
        prompt_profile="standard",
        context_policy="rolling",
        phase1_score=0.62,
    )

    assert len(economy_prompt) < len(standard_prompt)
    assert '"direction": "BULLISH|BEARISH|NEUTRAL"' in economy_prompt


def test_should_request_review_on_phase1_conflict():
    review = should_request_review(
        primary_result=GeminiAnalysisResult(
            direction="BULLISH",
            magnitude=0.75,
            confidence=0.82,
            rationale="Strong outlook",
            catalyst_type="GUIDANCE_UP",
            euphemism_count=0,
        ),
        phase1_raw_score=-0.71,
        phase1_confidence=0.81,
        important_chunk=True,
        section_type=SectionType.Q_AND_A,
        current_chunk="We are seeing some headwinds despite maintaining guidance.",
        integrity_valid=True,
        integrity_reason="ok",
        primary_parse_failed=False,
    )

    assert review.needs_review is True
    assert review.reason == "phase1_direction_conflict"


async def _fake_generate_content(*, model: str, contents: str, config: dict) -> str:
    if model == "gemini-3-flash-preview":
        return json.dumps(
            {
                "direction": "BULLISH",
                "magnitude": 0.45,
                "confidence": 0.55,
                "rationale": "Demand appears resilient.",
                "catalyst_type": "GUIDANCE_HOLD",
                "euphemism_count": 0,
                "negative_word_ratio": 0.15,
                "cot_reasoning": "Low-confidence first pass.",
            }
        )

    return json.dumps(
        {
            "direction": "BULLISH",
            "magnitude": 0.72,
            "confidence": 0.88,
            "rationale": "Demand and guidance commentary support a positive view.",
            "catalyst_type": "GUIDANCE_UP",
            "euphemism_count": 1,
            "negative_word_ratio": 0.08,
            "cot_reasoning": "Adjudication resolved the low-confidence ambiguity.",
        }
    )


def test_analysis_service_caps_live_path_at_two_calls(monkeypatch):
    service = AnalysisService()
    calls: list[str] = []

    async def _counting_generate_content(*, model: str, contents: str, config: dict) -> str:
        calls.append(model)
        return await _fake_generate_content(model=model, contents=contents, config=config)

    monkeypatch.setattr(gemini_client, "generate_content", _counting_generate_content)

    result = asyncio.run(
        service.analyze(
            ticker="NVDA",
            current_chunk="Our outlook remains constructive but there are some near-term headwinds.",
            context_chunks=[
                ChunkRecord(
                    sequence=1,
                    text_chunk="Our outlook remains constructive but there are some",
                    timestamp=1,
                )
            ],
            market_data=MarketData(volume_ratio=2.9, gap_pct=3.1, earnings_surprise_pct=12.0),
            section_type=SectionType.Q_AND_A,
            request_priority=8,
            is_final=False,
            phase1_result=Phase1ScoreResult(
                raw_score=0.40,
                confidence=0.75,
                provider="finbert_phase1",
                rationale_hint="Positive but mixed language",
            ),
        )
    )

    assert len(calls) == 2
    assert calls == ["gemini-3-flash-preview", "gemini-3-pro-preview"]
    assert result.model_route == "gemini-3-flash-preview->gemini-3-pro-preview"


def test_health_and_stats_include_routing_fields():
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        stats = client.get("/stats")

        assert health.status_code == 200
        assert stats.status_code == 200
        assert "primary_model" in health.json()
        assert "review_model" in health.json()
        assert "route_counts" in stats.json()
        assert "flash_only_rate" in stats.json()
        assert "pro_escalation_rate" in stats.json()
        assert "economy_prompt_rate" in stats.json()
