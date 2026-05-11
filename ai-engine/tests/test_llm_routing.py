from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from config import get_settings
from core.analysis_service import AnalysisService
from core.context_manager import ChunkRecord
from core.external_retriever import ExternalDocument, external_retriever
from core.gemini_client import gemini_client
from core.llm_consistency import should_request_review
from core.llm_router import decide_route
from core.phase1_scorer import Phase1ScoreResult
from core.prompt_builder import build_prompt
from main import create_app
from models.request_models import MarketData, SectionType
from models.signal_models import GeminiAnalysisResult
from src.graph.nodes.agent import agent as agent_node
from src.graph.nodes.rag_decision import rag_decision
from src.graph.nodes.relevance_check import relevance_check
from src.graph.nodes.retrieve import retrieve
from src.graph.nodes.rewrite import rewrite


@pytest.fixture(autouse=True)
def clear_external_retriever(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_PATH", raising=False)
    get_settings.cache_clear()
    external_retriever.reset_backend()
    external_retriever.clear()
    yield
    external_retriever.clear()
    external_retriever.reset_backend()
    get_settings.cache_clear()


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
    if "use_external_rag" in contents:
        return json.dumps(
            {
                "use_external_rag": False,
                "decision_confidence": 0.82,
                "retrieval_reason": "chunk_is_self_contained",
                "external_query": "",
                "preferred_sources": [],
                "lookback_days": 7,
            }
        )
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


def test_analysis_service_caps_live_path_at_three_calls(monkeypatch):
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
            chunk_timestamp=1,
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

    assert len(calls) == 3
    assert calls == [
        "gemini-3-flash-preview",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
    ]
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


def test_agent_initializes_external_rag_defaults():
    state = asyncio.run(
        agent_node(
            {
                "ticker": "NVDA",
                "current_chunk": "Could you elaborate on the guidance update?",
                "context_chunks": [
                    ChunkRecord(
                        sequence=3,
                        text_chunk="We raised guidance after the quarter.",
                        timestamp=3,
                    )
                ],
                "current_market_data": MarketData(volume_ratio=2.0, vix=18.0),
                "section_type": SectionType.Q_AND_A,
                "chunk_timestamp": 3,
                "request_priority": 5,
                "is_final": False,
                "phase1_raw_score": 0.20,
                "phase1_confidence": 0.75,
            }
        )
    )

    assert state["route_profile"] == "standard"
    assert state["use_external_rag"] is False
    assert state["external_docs"] == []


def test_rag_decision_can_enable_external_rag(monkeypatch):
    async def _decision(*, model: str, contents: str, config: dict) -> str:
        return json.dumps(
            {
                "use_external_rag": True,
                "decision_confidence": 0.91,
                "retrieval_reason": "recent guidance references imply external evidence",
                "external_query": "NVDA guidance update margins recent filing news",
                "preferred_sources": ["filing", "news"],
                "lookback_days": 45,
            }
        )

    monkeypatch.setattr(gemini_client, "generate_content", _decision)

    state = asyncio.run(
        rag_decision(
            {
                "ticker": "NVDA",
                "current_chunk": "Can you expand on the guidance update?",
                "context_chunks": [],
                "current_market_data": MarketData(volume_ratio=2.0, vix=18.0),
                "section_type": SectionType.Q_AND_A,
                "chunk_timestamp": 1741827000,
                "primary_model": "gemini-3-flash-preview",
                "llm_call_count": 0,
                "estimated_prompt_tokens_consumed": 0,
                "estimated_output_tokens_consumed": 0,
            }
        )
    )

    assert state["use_external_rag"] is True
    assert state["preferred_sources"] == ["filing", "news"]
    assert state["lookback_days"] == 30
    assert "guidance update" in state["external_query"].lower()


def test_retrieve_external_filters_future_docs_and_lookback_window():
    external_retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="filing-1",
                ticker="NVDA",
                title="8-K guidance update",
                text="The company raised full-year guidance and margin outlook.",
                published_at=1741826900,
                source_type="filing",
                form_type="8-K",
                importance=0.95,
            ),
            ExternalDocument(
                doc_id="future-news",
                ticker="NVDA",
                title="Post-call article",
                text="Article published after the chunk timestamp.",
                published_at=1741827100,
                source_type="news",
                importance=0.70,
            ),
            ExternalDocument(
                doc_id="old-news",
                ticker="NVDA",
                title="Old product article",
                text="Article outside the lookback window.",
                published_at=1740000000,
                source_type="news",
                importance=0.70,
            ),
        ]
    )

    state = asyncio.run(
        retrieve(
            {
                "ticker": "NVDA",
                "current_chunk": "Could you elaborate on the updated guidance?",
                "external_query": "NVDA updated guidance margin outlook",
                "chunk_timestamp": 1741827000,
                "preferred_sources": ["filing", "news"],
                "lookback_days": 7,
                "external_retrieval_attempts": 0,
            }
        )
    )

    assert [doc.doc_id for doc in state["external_docs"]] == ["filing-1"]
    assert state["external_retrieval_attempts"] == 1


def test_rewrite_promotes_external_query_when_first_retrieval_is_weak(monkeypatch):
    external_retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="filing-1",
                ticker="NVDA",
                title="8-K guidance update",
                text="The company raised full-year guidance and margin outlook.",
                published_at=1741826900,
                source_type="filing",
                form_type="8-K",
                importance=0.95,
            )
        ]
    )

    state = asyncio.run(
        retrieve(
            {
                "ticker": "NVDA",
                "current_chunk": "Can you elaborate on that?",
                "external_query": "NVDA elaborate that",
                "chunk_timestamp": 1741827000,
                "preferred_sources": ["filing"],
                "lookback_days": 7,
                "external_retrieval_attempts": 0,
            }
        )
    )

    assert state["external_docs"] == []

    async def _rewrite_response(*, model: str, contents: str, config: dict) -> str:
        return json.dumps(
            {
                "external_query": "NVDA raised full-year guidance margin outlook filing",
                "rewrite_reason": "added the missing guidance event terms",
            }
        )

    monkeypatch.setattr(gemini_client, "generate_content", _rewrite_response)
    rewritten_state = asyncio.run(
        rewrite(
            {
                **state,
                "section_type": SectionType.Q_AND_A,
                "context_chunks": [
                    ChunkRecord(
                        sequence=4,
                        text_chunk="We are raising full-year guidance and expect stronger margins next quarter.",
                        timestamp=1741826800,
                    )
                ],
                "primary_model": "gemini-3-flash-preview",
                "rewrite_reason": "low_relevance",
                "rewrite_count": 0,
                "llm_call_count": 0,
                "estimated_prompt_tokens_consumed": 0,
                "estimated_output_tokens_consumed": 0,
            }
        )
    )
    rewritten_state = asyncio.run(retrieve(rewritten_state))

    assert rewritten_state["rewrite_count"] == 1
    assert rewritten_state["external_docs"]
    assert "guidance" in rewritten_state["external_query"].lower()


def test_relevance_check_requests_query_rewrite_when_retrieval_is_weak():
    state = asyncio.run(
        relevance_check(
            {
                "use_external_rag": True,
                "rewrite_count": 0,
                "external_docs": [],
            }
        )
    )

    assert state["has_external_evidence"] is False
    assert state["should_rewrite"] is True
    assert state["rewrite_reason"] == "low_relevance"


def test_analysis_service_injects_external_evidence_into_prompt(monkeypatch):
    service = AnalysisService()
    prompts: list[str] = []
    external_retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="filing-1",
                ticker="NVDA",
                title="8-K guidance update",
                text="The company raised full-year guidance on sustained data center demand.",
                published_at=2,
                source_type="filing",
                form_type="8-K",
                importance=0.95,
            )
        ]
    )

    async def _capturing_generate_content(*, model: str, contents: str, config: dict) -> str:
        prompts.append(contents)
        if "use_external_rag" in contents:
            return json.dumps(
                {
                    "use_external_rag": True,
                    "decision_confidence": 0.88,
                    "retrieval_reason": "the chunk references prior guidance",
                    "external_query": "NVDA guidance update filing",
                    "preferred_sources": ["filing"],
                    "lookback_days": 7,
                }
            )
        return json.dumps(
            {
                "direction": "BULLISH",
                "magnitude": 0.61,
                "confidence": 0.93,
                "rationale": "External filing confirms stronger guidance and demand.",
                "catalyst_type": "GUIDANCE_UP",
                "euphemism_count": 0,
                "negative_word_ratio": 0.05,
                "cot_reasoning": "External evidence grounds the ambiguous follow-up.",
            }
        )

    monkeypatch.setattr(gemini_client, "generate_content", _capturing_generate_content)

    result = asyncio.run(
        service.analyze(
            ticker="NVDA",
            current_chunk="Can you elaborate on the guidance update?",
            context_chunks=[
                ChunkRecord(
                    sequence=2,
                    text_chunk="We are raising full-year guidance on sustained data center demand.",
                    timestamp=2,
                )
            ],
            market_data=MarketData(volume_ratio=3.0, gap_pct=3.5, earnings_surprise_pct=12.0),
            section_type=SectionType.Q_AND_A,
            chunk_timestamp=3,
            request_priority=7,
            is_final=False,
            phase1_result=Phase1ScoreResult(
                raw_score=0.35,
                confidence=0.78,
                provider="finbert_phase1",
                rationale_hint="Positive guidance language",
            ),
        )
    )

    assert result.direction == "BULLISH"
    assert len(prompts) == 2
    assert "## External evidence" in prompts[1]
    assert "8-k guidance update" in prompts[1].lower()
