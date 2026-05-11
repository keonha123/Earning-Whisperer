from __future__ import annotations

import os
import time

import pytest

from config import get_settings
from core.context_manager import ChunkRecord
from core.external_retriever import ExternalDocument, external_retriever
from core.phase1_scorer import Phase1ScoreResult
from models.request_models import MarketData, SectionType
from src.graph.nodes.agent import agent as agent_node
from src.graph.nodes.build_prompt import build_prompt_node
from src.graph.nodes.primary_llm_call import primary_llm_call
from src.graph.nodes.rag_decision import rag_decision
from src.graph.nodes.relevance_check import relevance_check
from src.graph.nodes.retrieve import retrieve


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI_RAG_TEST") != "1",
    reason="Set RUN_LIVE_GEMINI_RAG_TEST=1 to run the live Gemini RAG test.",
)


@pytest.mark.asyncio
async def test_live_gemini_rag_uses_external_evidence():
    """Manual integration test for the live Gemini + external RAG path.

    This test intentionally calls real Gemini. It also writes one synthetic
    external evidence document to the configured retriever backend. If
    ai-engine/.env is configured for Qdrant, this will upsert into Qdrant.
    """

    settings = get_settings()
    if not settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY is required for the live Gemini RAG test.")

    if settings.vector_store_backend == "qdrant" and settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            pytest.skip("OPENAI_API_KEY is required for Qdrant + OpenAI embedding retrieval.")

    external_retriever.reset_backend()

    now = int(time.time())
    unique_marker = f"ew-live-rag-marker-{now}"
    external_retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id=f"live-rag-test:{unique_marker}",
                ticker="NVDA",
                title="NVDA live RAG test guidance marker",
                text=(
                    f"{unique_marker}. NVIDIA raised full-year data center guidance "
                    "after stronger Blackwell accelerator demand and improving supply."
                ),
                published_at=now - 60,
                source_type="news",
                url="https://example.com/live-rag-test",
                importance=0.95,
                metadata={"provider": "manual-live-test", "marker": unique_marker},
            )
        ]
    )

    state = {
        "ticker": "NVDA",
        "current_chunk": (
            f"Can you connect the guidance update to the recent external report "
            f"with marker {unique_marker}?"
        ),
        "context_chunks": [
            ChunkRecord(
                sequence=1,
                text_chunk=(
                    "Management said the updated outlook depends on external demand "
                    "signals seen after the quarter."
                ),
                timestamp=now - 120,
            )
        ],
        "current_market_data": MarketData(
            current_price=900.0,
            price_change_pct=2.4,
            volume_ratio=3.2,
            gap_pct=1.8,
            vix=17.5,
            earnings_surprise_pct=9.0,
        ),
        "section_type": SectionType.Q_AND_A,
        "chunk_timestamp": now,
        "request_priority": 8,
        "is_final": False,
        "phase1_raw_score": 0.40,
        "phase1_confidence": 0.80,
        "phase1_result": Phase1ScoreResult(
            raw_score=0.40,
            confidence=0.80,
            provider="manual-live-test",
            rationale_hint="Guidance update references external evidence.",
        ),
    }

    state = await agent_node(state)
    state = await rag_decision(state)
    print("RAG decision:", state.get("rag_decision_result_text"))
    assert state["use_external_rag"] is True, state.get("rag_decision_result_text")

    state = await retrieve(state)
    print("Retrieved docs:", [(doc.doc_id, doc.score, doc.title) for doc in state["external_docs"]])
    assert any(unique_marker in doc.text for doc in state["external_docs"])

    state = await relevance_check(state)
    assert state["has_external_evidence"] is True

    state = await build_prompt_node(state)
    assert "## External evidence" in state["contents"]
    assert unique_marker in state["contents"]

    state = await primary_llm_call(state)
    print("Primary Gemini response:", state["primary_result_text"])

    stats = external_retriever.get_stats()
    assert stats["upserted_chunks"] >= 1
    assert stats["retrieval_count"] >= 1
    assert state["primary_result_text"].strip()
