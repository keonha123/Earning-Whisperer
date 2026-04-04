from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from ..core.context_manager import ChunkRecord, ContextManager
from ..core.integrity_validator import _detect_direction
from ..core.score_normalizer import compute_raw_score, compute_raw_score_batch
from ..models.signal_models import GeminiAnalysisResult


def test_tetlock_penalty_reduces_bearish_magnitude_and_keeps_neutral_unbiased():
    bearish = GeminiAnalysisResult(
        direction="BEARISH",
        magnitude=0.95,
        confidence=1.0,
        rationale="High-confidence caution",
        catalyst_type="GUIDANCE_DOWN",
        euphemism_count=0,
    )
    neutral = GeminiAnalysisResult(
        direction="NEUTRAL",
        magnitude=0.95,
        confidence=1.0,
        rationale="High-confidence neutral framing",
        catalyst_type="MACRO_COMMENTARY",
        euphemism_count=0,
    )

    bearish_score = compute_raw_score(bearish)
    neutral_score = compute_raw_score(neutral)

    assert bearish_score == pytest.approx(-0.90, abs=1e-6)
    assert neutral_score == pytest.approx(0.0, abs=1e-6)


def test_batch_tetlock_adjustment_is_directionally_symmetric():
    results = [
        GeminiAnalysisResult(
            direction="BULLISH",
            magnitude=0.95,
            confidence=1.0,
            rationale="Strong upside",
            catalyst_type="EARNINGS_BEAT",
            euphemism_count=0,
        ),
        GeminiAnalysisResult(
            direction="BEARISH",
            magnitude=0.95,
            confidence=1.0,
            rationale="Strong downside",
            catalyst_type="GUIDANCE_DOWN",
            euphemism_count=0,
        ),
        GeminiAnalysisResult(
            direction="NEUTRAL",
            magnitude=0.95,
            confidence=1.0,
            rationale="Balanced commentary",
            catalyst_type="MACRO_COMMENTARY",
            euphemism_count=0,
        ),
    ]

    scores = compute_raw_score_batch(results)

    assert np.allclose(scores, np.array([0.90, -0.90, 0.0]))


@pytest.mark.asyncio
async def test_context_manager_uses_session_key_named_argument():
    manager = ContextManager(history_size=3, session_ttl=60)

    await manager.update(
        session_key="NVDA:call-001",
        chunk=ChunkRecord(sequence=1, text_chunk="prepared remarks", timestamp=1),
    )

    context = await manager.get_context("NVDA:call-001")

    assert len(context) == 1
    assert context[0].text_chunk == "prepared remarks"


@pytest.mark.asyncio
async def test_cleanup_expired_rechecks_session_state_before_deletion():
    manager = ContextManager(history_size=3, session_ttl=1)
    session_key = "NVDA:call-001"

    await manager.update(
        session_key=session_key,
        chunk=ChunkRecord(sequence=1, text_chunk="old chunk", timestamp=1),
    )
    manager._sessions[session_key].last_updated = time.time() - 5

    lock = await manager._get_or_create_lock(session_key)
    async with lock:
        cleanup_task = asyncio.create_task(manager.cleanup_expired())
        await asyncio.sleep(0.01)
        manager._sessions[session_key].last_updated = time.time()
        manager._sessions[session_key].chunks.append(
            ChunkRecord(sequence=2, text_chunk="fresh chunk", timestamp=2)
        )

    cleaned = await cleanup_task
    context = await manager.get_context(session_key)

    assert cleaned == 0
    assert [chunk.text_chunk for chunk in context] == ["old chunk", "fresh chunk"]


def test_negation_window_handles_not_at_all_growth_phrase():
    direction = _detect_direction("there is not at all growth in revenues this quarter")
    assert direction != "BULLISH"
