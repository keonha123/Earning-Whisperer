from __future__ import annotations

import asyncio
import json

import pytest

from config import Settings, get_settings
from core.analysis_service import AnalysisService
from core.context_manager import ChunkRecord
from core.gemini_client import gemini_client
from core.llm_router import decide_route
from models.request_models import MarketData, SectionType
from models.signal_models import GeminiAnalysisResult
from src.graph.nodes.parse_and_finalize import parse_and_finalize


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_legacy_model_mapping_does_not_override_explicit_gemini3_fields():
    settings = Settings(
        gemini_primary_model="gemini-3-flash-preview",
        gemini_review_model="gemini-3-pro-preview",
        gemini_fast_model="legacy-fast-model",
        gemini_model="legacy-review-model",
    )

    assert settings.gemini_primary_model == "gemini-3-flash-preview"
    assert settings.gemini_review_model == "gemini-3-pro-preview"


def test_legacy_model_mapping_still_fills_when_new_fields_are_absent():
    settings = Settings(
        gemini_fast_model="legacy-fast-model",
        gemini_model="legacy-review-model",
    )

    assert settings.gemini_primary_model == "legacy-fast-model"
    assert settings.gemini_review_model == "legacy-review-model"


def test_novelty_threshold_can_force_delta_context_for_important_chunks(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_NOVELTY_THRESHOLD", "0.95")
    decision = decide_route(
        current_chunk="Revenue grew 10 percent and margins improved in the quarter.",
        context_chunks=[
            ChunkRecord(
                sequence=1,
                text_chunk="Revenue grew 10 percent and margins improved",
                timestamp=1,
            )
        ],
        market_data=MarketData(volume_ratio=1.2, vix=16.0),
        section_type=SectionType.Q_AND_A,
        request_priority=5,
        is_final=False,
        phase1_raw_score=0.20,
    )

    assert decision.route_profile == "standard"
    assert decision.context_policy == "delta"


def test_novelty_threshold_allows_rolling_context_when_overlap_is_low(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_NOVELTY_THRESHOLD", "0.10")
    decision = decide_route(
        current_chunk="The guidance commentary was stronger than expected.",
        context_chunks=[
            ChunkRecord(
                sequence=1,
                text_chunk="Prepared remarks focused on supply chain normalization.",
                timestamp=1,
            )
        ],
        market_data=MarketData(volume_ratio=1.2, vix=16.0),
        section_type=SectionType.Q_AND_A,
        request_priority=5,
        is_final=False,
        phase1_raw_score=0.20,
    )

    assert decision.route_profile == "standard"
    assert decision.context_policy == "rolling"


def test_direct_prompt_analysis_requires_explicit_opt_in():
    service = AnalysisService()

    with pytest.raises(RuntimeError, match="bypasses live routing"):
        asyncio.run(service.analyze_prompt('{"direction":"NEUTRAL"}'))


def test_live_path_falls_back_cleanly_when_one_call_budget_blocks_review(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_MAX_CALLS_PER_CHUNK", "1")
    service = AnalysisService()

    async def _invalid_response(*, model: str, contents: str, config: dict) -> str:
        return "not-json"

    monkeypatch.setattr(gemini_client, "generate_content", _invalid_response)

    result = asyncio.run(
        service.analyze(
            ticker="NVDA",
            current_chunk="Demand commentary remained mixed but constructive.",
            context_chunks=[
                ChunkRecord(sequence=1, text_chunk="Demand commentary remained mixed", timestamp=1)
            ],
            market_data=MarketData(volume_ratio=2.0, vix=18.0),
            section_type=SectionType.Q_AND_A,
            chunk_timestamp=1,
            request_priority=8,
            is_final=False,
            phase1_result=type(
                "Phase1Result",
                (),
                {"raw_score": 0.22, "confidence": 0.80},
            )(),
        )
    )

    assert result.direction == "NEUTRAL"
    assert result.model_route == "gemini-3-flash-preview->fallback"


def test_parse_and_finalize_uses_fallback_when_no_parsed_result_exists():
    state = {
        "primary_model": "gemini-3-flash-preview",
        "review_model": "gemini-3-pro-preview",
        "primary_config": {"max_output_tokens": 384},
        "estimated_prompt_tokens": 120,
        "estimated_prompt_tokens_consumed": 120,
        "estimated_output_tokens_consumed": 384,
    }

    final_state = asyncio.run(parse_and_finalize(state))

    assert final_state["result"].direction == "NEUTRAL"
    assert final_state["result"].model_route == "gemini-3-flash-preview->fallback"


def test_modern_sdk_generation_retries_without_thinking_config(monkeypatch):
    from core import gemini_client as gemini_client_module

    class FakeThinkingConfig:
        def __init__(self, *, level: str):
            self.level = level

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        text = json.dumps(
            {
                "direction": "NEUTRAL",
                "magnitude": 0.0,
                "confidence": 0.0,
                "rationale": "ok",
                "catalyst_type": "MACRO_COMMENTARY",
                "euphemism_count": 0,
                "negative_word_ratio": 0.0,
                "cot_reasoning": "ok",
            }
        )

    class FakeModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, *, model: str, contents: str, config):
            self.calls.append(config)
            if len(self.calls) == 1:
                raise TypeError("thinking_config unsupported")
            return FakeResponse()

    fake_models = FakeModels()

    class FakeClient:
        def __init__(self, *, api_key: str):
            self.api_key = api_key
            self.models = fake_models

    fake_modern_genai = type("FakeModernGenAI", (), {"Client": FakeClient})
    fake_modern_types = type(
        "FakeModernTypes",
        (),
        {
            "ThinkingConfig": FakeThinkingConfig,
            "GenerateContentConfig": FakeGenerateContentConfig,
        },
    )

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_client_module, "modern_genai", fake_modern_genai)
    monkeypatch.setattr(gemini_client_module, "modern_types", fake_modern_types)
    gemini_client._modern_client = None
    gemini_client._modern_client_api_key = None

    response = gemini_client._generate_with_modern_sdk(
        "gemini-3-flash-preview",
        "prompt",
        {
            "system_instruction": "system",
            "max_output_tokens": 128,
            "response_mime_type": "application/json",
            "thinking_level": "minimal",
        },
    )

    assert json.loads(response)["direction"] == "NEUTRAL"
    assert len(fake_models.calls) == 2
    assert "thinking_config" in fake_models.calls[0].kwargs
    assert "thinking_config" not in fake_models.calls[1].kwargs


def test_direct_prompt_analysis_can_still_run_for_explicit_research_usage(monkeypatch):
    service = AnalysisService()

    async def _fake_generate_content(*, model: str, contents: str, config: dict) -> str:
        return json.dumps(
            {
                "direction": "BULLISH",
                "magnitude": 0.6,
                "confidence": 0.8,
                "rationale": "Research helper path.",
                "catalyst_type": "GUIDANCE_UP",
                "euphemism_count": 0,
                "negative_word_ratio": 0.1,
                "cot_reasoning": "ok",
            }
        )

    monkeypatch.setattr(gemini_client, "generate_content", _fake_generate_content)
    result = asyncio.run(
        service.analyze_prompt(
            "prompt",
            allow_direct_prompt=True,
        )
    )

    assert isinstance(result, GeminiAnalysisResult)
    assert result.direction == "BULLISH"
