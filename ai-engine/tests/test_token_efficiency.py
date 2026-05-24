from __future__ import annotations

import asyncio
import json

import pytest

try:
    from ..config import get_settings
    from ..core.gemini_client import gemini_client
    from ..core.llm_consistency import should_request_review
    from ..core.context_manager import ChunkRecord
    from ..core.prompt_builder import build_prompt
    from ..core.token_budgeter import estimate_tokens
    from ..models.request_models import MarketData, SectionType
    from ..models.signal_models import GeminiAnalysisResult
except ImportError:  # pragma: no cover - direct pytest execution from ai-engine/
    from config import get_settings
    from core.gemini_client import gemini_client
    from core.llm_consistency import should_request_review
    from core.context_manager import ChunkRecord
    from core.prompt_builder import build_prompt
    from core.token_budgeter import estimate_tokens
    from models.request_models import MarketData, SectionType
    from models.signal_models import GeminiAnalysisResult


@pytest.fixture(autouse=True)
def clear_settings_and_cache():
    get_settings.cache_clear()
    gemini_client._response_cache.clear()
    gemini_client._inflight_requests.clear()
    yield
    get_settings.cache_clear()
    gemini_client._response_cache.clear()
    gemini_client._inflight_requests.clear()


def test_prompt_builder_compacts_rolling_context_when_budget_is_small(monkeypatch):
    monkeypatch.setenv("ANALYSIS_CONTEXT_TOKEN_BUDGET", "128")
    monkeypatch.setenv("ANALYSIS_CONTEXT_MAX_CHUNKS", "2")
    monkeypatch.setenv("ANALYSIS_CONTEXT_CHUNK_CHARS", "80")
    monkeypatch.setenv("ANALYSIS_CURRENT_CHUNK_CHARS", "200")
    get_settings.cache_clear()

    context = [
        ChunkRecord(sequence=1, text_chunk="First chunk " + ("alpha " * 80), timestamp=1),
        ChunkRecord(sequence=2, text_chunk="Second chunk " + ("beta " * 80), timestamp=2),
        ChunkRecord(sequence=3, text_chunk="Third chunk " + ("gamma " * 80), timestamp=3),
        ChunkRecord(sequence=4, text_chunk="Fourth chunk " + ("delta " * 80), timestamp=4),
    ]

    prompt = build_prompt(
        ticker="NVDA",
        current_chunk="Current chunk " + ("signal " * 120),
        context_chunks=context,
        market_data=MarketData(current_price=900.0, volume_ratio=2.2, rsi_14=63.0),
        prompt_profile="standard",
        context_policy="rolling",
        phase1_score=0.55,
    )

    assert "older chunk(s) omitted" in prompt
    assert "[Chunk 4]" in prompt
    assert "[Chunk 1]" not in prompt
    assert len(prompt) < 1600


def test_review_is_suppressed_for_strong_phase1_alignment_near_threshold():
    review = should_request_review(
        primary_result=GeminiAnalysisResult(
            direction="BULLISH",
            magnitude=0.64,
            confidence=0.63,
            rationale="Demand and guidance remain constructive.",
            catalyst_type="GUIDANCE_UP",
            euphemism_count=0,
        ),
        phase1_raw_score=0.58,
        phase1_confidence=0.82,
        important_chunk=True,
        section_type=SectionType.Q_AND_A,
        current_chunk="We are seeing strong enterprise demand and maintaining a constructive outlook.",
        integrity_valid=True,
        integrity_reason="ok",
        primary_parse_failed=False,
    )

    assert review.needs_review is False


def test_gemini_client_reuses_exact_prompt_cache(monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_generate_sync(model: str, contents: str, config: dict) -> str:
        calls.append((model, contents))
        return json.dumps(
            {
                "direction": "NEUTRAL",
                "magnitude": 0.0,
                "confidence": 0.0,
                "rationale": "cached",
                "catalyst_type": "MACRO_COMMENTARY",
                "euphemism_count": 0,
                "negative_word_ratio": 0.0,
                "cot_reasoning": "cached",
            }
        )

    monkeypatch.setenv("GEMINI_RESPONSE_CACHE_ENABLED", "true")
    monkeypatch.setenv("GEMINI_RESPONSE_CACHE_TTL_SECONDS", "300")
    monkeypatch.setenv("GEMINI_RESPONSE_CACHE_MAX_ENTRIES", "8")
    get_settings.cache_clear()
    monkeypatch.setattr(gemini_client, "_generate_sync", _fake_generate_sync)

    async def _run():
        first = await gemini_client.generate_content(
            model="gemini-2.5-flash-preview",
            contents="same prompt",
            config={"max_output_tokens": 128, "thinking_level": "minimal"},
        )
        second = await gemini_client.generate_content(
            model="gemini-2.5-flash-preview",
            contents="same prompt",
            config={"max_output_tokens": 128, "thinking_level": "minimal"},
        )
        return first, second

    first, second = asyncio.run(_run())

    assert first == second
    assert len(calls) == 1


def test_gemini_client_coalesces_inflight_identical_requests(monkeypatch):
    calls: list[str] = []

    def _fake_generate_sync(model: str, contents: str, config: dict):
        calls.append(contents)
        return (
            json.dumps(
                {
                    "direction": "NEUTRAL",
                    "magnitude": 0.0,
                    "confidence": 0.0,
                    "rationale": "ok",
                    "catalyst_type": "MACRO_COMMENTARY",
                    "euphemism_count": 0,
                    "negative_word_ratio": 0.0,
                }
            ),
            {"prompt_tokens": 12, "output_tokens": 8, "total_tokens": 20, "estimated_cost_usd": 0.0},
        )

    monkeypatch.setenv("GEMINI_RESPONSE_CACHE_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(gemini_client, "_generate_sync", _fake_generate_sync)

    async def _run():
        return await asyncio.gather(
            gemini_client.generate_content_with_metadata(
                model="gemini-2.5-flash-preview",
                contents="same prompt",
                config={"max_output_tokens": 128},
            ),
            gemini_client.generate_content_with_metadata(
                model="gemini-2.5-flash-preview",
                contents="same prompt",
                config={"max_output_tokens": 128},
            ),
        )

    first, second = asyncio.run(_run())

    assert len(calls) == 1
    assert first.text == second.text
    assert second.coalesced is True or first.coalesced is True


def test_prompt_builder_enforces_absolute_prompt_token_ceiling(monkeypatch):
    monkeypatch.setenv("ANALYSIS_MAX_PROMPT_TOKENS", "1024")
    monkeypatch.setenv("ANALYSIS_CURRENT_CHUNK_CHARS", "6000")
    monkeypatch.setenv("ANALYSIS_CONTEXT_CHUNK_CHARS", "3000")
    monkeypatch.setenv("ANALYSIS_CONTEXT_MAX_CHUNKS", "8")
    monkeypatch.setenv("ANALYSIS_CONTEXT_TOKEN_BUDGET", "6000")
    get_settings.cache_clear()

    oversized_chunk = "Management commentary " + ("growth margin demand " * 800)
    context = [
        ChunkRecord(sequence=i, text_chunk=oversized_chunk, timestamp=i)
        for i in range(1, 7)
    ]
    prompt = build_prompt(
        ticker="MSFT",
        current_chunk=oversized_chunk,
        context_chunks=context,
        market_data=MarketData(
            current_price=415.0,
            price_change_pct=2.5,
            volume_ratio=3.2,
            vix=17.0,
            earnings_surprise_pct=12.0,
            gap_pct=4.1,
            liquidity_score=0.95,
            rsi_14=67.0,
            macd_signal=0.03,
            put_call_ratio=0.8,
            current_iv=0.42,
            iv_rank=62.0,
            short_interest_pct=2.1,
            days_to_cover=1.2,
        ),
        prompt_profile="standard",
        context_policy="rolling",
        phase1_score=0.64,
    )

    assert estimate_tokens(prompt) <= 1024
    assert "Context compacted for token budget." in prompt
