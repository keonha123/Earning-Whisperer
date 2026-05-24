from __future__ import annotations

from core.prompt_builder import build_prompt
from models.request_models import AnalyzeRequest, MarketData
from services.canonical_bundle_service import CanonicalBundleService


def test_analyze_request_accepts_canonical_bundle_and_source_health() -> None:
    payload = AnalyzeRequest.model_validate(
        {
            "ticker": "NVDA",
            "prompt": "Raised guidance and strong AI demand.",
            "source_type": "EARNINGS_CALL",
            "canonical_bundle": {
                "company": {"ticker": "NVDA", "company_name": "NVIDIA", "sector_code": "semis"},
                "earnings_event": {"event_id": "evt_nvda", "fiscal_quarter": "2026Q1"},
                "guidance": {"direction": "UP", "summary": "Raised revenue outlook"},
            },
            "source_health": [
                {"source": "benzinga_transcripts", "status": "HEALTHY", "freshness_seconds": 45},
                {"source": "x_posts", "status": "DEGRADED", "freshness_seconds": 5400},
            ],
        }
    )

    assert payload.canonical_bundle is not None
    assert payload.canonical_bundle.company.company_name == "NVIDIA"
    assert payload.source_health[1].source == "x_posts"


def test_canonical_bundle_service_builds_feature_bundle_and_health_summary() -> None:
    request = AnalyzeRequest.model_validate(
        {
            "ticker": "NVDA",
            "prompt": "Raised guidance and strong AI demand.",
            "source_type": "EARNINGS_CALL",
            "market_data": {"current_price": 950.0, "volume_ratio": 2.3, "vix": 18.5},
            "canonical_bundle": {
                "company": {"ticker": "NVDA", "company_name": "NVIDIA", "sector_code": "semis", "market_cap_bucket": "mega"},
                "earnings_event": {"event_id": "evt_nvda", "fiscal_quarter": "2026Q1", "market_session": "post_market"},
                "transcript": {"prepared_summary": "Raised guidance.", "qa_summary": "Demand remained strong.", "qna_sentiment_delta": 0.18, "prepared_vs_qa_gap": -0.04},
                "guidance": {"direction": "UP", "summary": "Raised revenue outlook", "margin_delta_pct": 1.6},
            },
            "source_health": [
                {"source": "benzinga_transcripts", "status": "HEALTHY", "freshness_seconds": 45},
                {"source": "x_posts", "status": "DEGRADED", "freshness_seconds": 5400},
            ],
        }
    )
    service = CanonicalBundleService()

    feature_bundle = service.build_feature_bundle(
        ticker=request.ticker,
        market_data=request.market_data,
        current_chunk=request.current_chunk,
        canonical_bundle=request.canonical_bundle,
        source_health=request.source_health,
    )

    assert feature_bundle["canonical_present"] is True
    assert feature_bundle["coverage"]["guidance"] is True
    assert feature_bundle["source_health_summary"]["degraded_count"] == 1
    assert feature_bundle["source_health_summary"]["stale_count"] == 1
    assert "GUIDANCE=UP" in feature_bundle["prompt_context"]


def test_build_prompt_accepts_route_profile_alias_and_feature_bundle_context() -> None:
    market_data = MarketData.model_validate({"current_price": 100.0, "volume_ratio": 1.8, "vix": 19.0})
    prompt = build_prompt(
        ticker="AAPL",
        current_chunk="Margins improved and guidance was raised.",
        context_chunks=["Previous quarter demand was mixed."],
        market_data=market_data,
        section_type="GUIDANCE",
        source_type="EARNINGS_CALL",
        route_profile="review",
        context_policy="rolling",
        phase1_score=0.44,
        feature_bundle_context="GUIDANCE=UP | QNA_SENTIMENT_DELTA=0.22 | CAP_BUCKET=mega",
    )

    assert "PROFILE: review" in prompt
    assert "SOURCE_TYPE: EARNINGS_CALL" in prompt
    assert "FEATURE_BUNDLE:" in prompt
