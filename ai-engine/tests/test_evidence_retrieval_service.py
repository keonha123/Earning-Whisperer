from __future__ import annotations

from fastapi.testclient import TestClient

import main
from core.prompt_builder import build_prompt
from core.trade_plan import build_trade_plan
from models.evidence_models import (
    ClaimDiffRequest,
    EvidenceDocument,
    EvidenceRetrievalRequest,
    EvidenceSourceType,
    FactCheckRequest,
    HistoricalClaim,
    ImpactChainRequest,
    ImpactDirection,
    OmissionAnalysisRequest,
    TradeExitPlanRequest,
)
from models.request_models import MarketData
from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
from services.evidence_retrieval_service import EvidenceRetrievalService


def _documents() -> list[EvidenceDocument]:
    return [
        EvidenceDocument(
            ticker="NVDA",
            source_type=EvidenceSourceType.EARNINGS_RELEASE,
            source="2026 Q1 earnings release",
            title="Q1 earnings release",
            published_at="2026-04-24",
            content="Gross margin improved sequentially and data center demand remained strong.",
            reliability_score=0.92,
        ),
        EvidenceDocument(
            ticker="NVDA",
            source_type=EvidenceSourceType.FILING,
            source="10-Q",
            title="Quarterly filing",
            published_at="2026-04-25",
            content="Management noted supply constraints and elevated infrastructure investment.",
            reliability_score=0.95,
        ),
    ]


def test_evidence_retrieval_builds_prompt_context_with_citations() -> None:
    service = EvidenceRetrievalService()
    result = service.retrieve(
        EvidenceRetrievalRequest(
            ticker="NVDA",
            query="gross margin improved sequentially",
            documents=_documents(),
        )
    )

    assert result.evidence
    assert result.coverage_score > 0.0
    assert "RAG_EVIDENCE:" in result.evidence_context
    assert "2026 Q1 earnings release" in result.evidence_context


def test_prompt_accepts_explicit_evidence_context() -> None:
    prompt = build_prompt(
        ticker="NVDA",
        current_chunk="Gross margin improved sequentially.",
        context_chunks=[],
        market_data=MarketData.model_validate({"current_price": 100.0}),
        section_type="Q_AND_A",
        source_type="EARNINGS_CALL",
        evidence_context="RAG_EVIDENCE:\n- EARNINGS_RELEASE | release | 2026-04-24 | confidence=0.88 | margin improved",
    )

    assert "EVIDENCE_LAYER:" in prompt
    assert "RAG_EVIDENCE:" in prompt


def test_fact_check_supported_and_contradicted() -> None:
    service = EvidenceRetrievalService()

    supported = service.fact_check(
        FactCheckRequest(
            ticker="NVDA",
            claim="Gross margin improved sequentially",
            documents=_documents(),
        )
    )
    contradicted = service.fact_check(
        FactCheckRequest(
            ticker="NVDA",
            claim="Gross margin improved sequentially",
            documents=[
                EvidenceDocument(
                    ticker="NVDA",
                    source_type=EvidenceSourceType.EARNINGS_RELEASE,
                    source="release",
                    content="Gross margin declined sequentially due to cost pressure.",
                    reliability_score=0.9,
                )
            ],
        )
    )

    assert supported.fact_check == "SUPPORTED"
    assert contradicted.fact_check == "CONTRADICTED"


def test_claim_diff_detects_directional_shift() -> None:
    service = EvidenceRetrievalService()
    result = service.claim_diff(
        ClaimDiffRequest(
            ticker="NVDA",
            current_claims=["We are accelerating infrastructure investment."],
            historical_claims=[
                HistoricalClaim(
                    ticker="NVDA",
                    topic="capex",
                    claim="Capex will remain disciplined.",
                    source="prior call",
                    confidence=0.82,
                )
            ],
        )
    )

    assert result.items[0].change_type == "DIRECTIONAL_SHIFT"
    assert result.max_risk_score >= 0.7


def test_omission_analysis_scores_missing_answer_slots() -> None:
    service = EvidenceRetrievalService()
    result = service.analyze_omission(
        OmissionAnalysisRequest(
            ticker="NVDA",
            question="What is the guidance margin pressure, timeframe, and cost driver?",
            answer="Component costs are the main driver.",
        )
    )

    assert "margin impact" in result.omitted_slots
    assert "timeframe" in result.omitted_slots
    assert result.omission_score > 0.5


def test_impact_chain_returns_nvda_related_names() -> None:
    service = EvidenceRetrievalService()
    result = service.impact_chain(
        ImpactChainRequest(
            source_ticker="NVDA",
            source_direction=ImpactDirection.BULLISH,
            catalyst="Data center GPU demand remained strong.",
            confidence=0.72,
        )
    )

    tickers = [item.ticker for item in result.impacted]
    assert "TSMC" in tickers
    assert result.impacted[0].impact_score >= result.impacted[-1].impact_score


def test_trade_plan_includes_auto_exit_plan() -> None:
    market_data = MarketData.model_validate({"current_price": 100.0, "atr_pct_14": 0.03, "gap_pct": 5.0})
    analysis = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.7,
        confidence=0.78,
        rationale="supported setup",
        catalyst_type="EARNINGS",
        metadata={"evidence_retrieval": {"coverage_score": 0.74}},
    )
    decision = StrategyDecision(
        strategy=StrategyName.PEAD,
        score=0.76,
        hold_days=3,
        rationale="continuation",
        metadata={"hold_tuning": {"mfe_mae_profile": {"expected_mfe_atr": 2.4, "expected_mae_atr": 1.1}}},
    )

    plan = build_trade_plan(market_data, decision, analysis)

    assert plan["auto_exit_plan"]["available"] is True
    assert plan["auto_exit_plan"]["stop_loss"]["price"] == plan["stop_loss"]
    assert plan["auto_exit_plan"]["take_profit"]["primary_price"] == plan["take_profit_1"]


def test_evidence_api_endpoints_smoke() -> None:
    client = TestClient(main.app)
    search = client.post(
        "/v1/engine/evidence/search",
        json={"ticker": "NVDA", "query": "gross margin improved", "documents": [item.model_dump(mode="json") for item in _documents()]},
    )
    impact = client.get("/v1/engine/impact-chain/NVDA?source_direction=BULLISH&confidence=0.72")
    exits = client.post(
        "/v1/engine/trade-exits/generate",
        json={
            "ticker": "NVDA",
            "strategy": "PEAD",
            "direction": "LONG",
            "confidence": 0.78,
            "hold_days": 3,
            "market_data": {"current_price": 100.0, "atr_pct_14": 0.03},
        },
    )

    assert search.status_code == 200
    assert search.json()["evidence"]
    assert impact.status_code == 200
    assert impact.json()["impacted"]
    assert exits.status_code == 200
    assert exits.json()["stop_loss"]["price"] < 100.0
