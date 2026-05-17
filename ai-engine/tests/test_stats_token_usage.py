from __future__ import annotations

from fastapi.testclient import TestClient

import main
from core.signal_data_hub import SignalDataHub
from core.token_budgeter import TokenUsageEvent
from services.canonical_bundle_service import SourceHealthTelemetry


def test_stats_exposes_token_cost_and_budget_fields() -> None:
    analysis_service = main.app.state.analysis_service
    analysis_service.route_counts.clear()
    analysis_service.route_counts.update({"gemini-3.1-flash-preview": 2, "gemini-3.1-pro-preview": 1})
    analysis_service.signal_data_hub = SignalDataHub()
    analysis_service.source_health_telemetry = SourceHealthTelemetry()
    analysis_service.token_budgeter._events.clear()
    analysis_service.token_budgeter.record(
        TokenUsageEvent(
            route_profile="economy",
            model="gemini-3.1-flash-preview",
            prompt_tokens=120,
            output_tokens=32,
            total_tokens=152,
            estimated_cost_usd=0.0123,
            cached=True,
            coalesced=False,
            approved_signal=True,
            budget_tokens=384,
        )
    )
    analysis_service.token_budgeter.record(
        TokenUsageEvent(
            route_profile="review",
            model="gemini-3.1-pro-preview",
            prompt_tokens=420,
            output_tokens=85,
            total_tokens=505,
            estimated_cost_usd=0.0456,
            cached=False,
            coalesced=True,
            approved_signal=False,
            budget_tokens=960,
        )
    )
    analysis_service.source_health_telemetry.record(
        {
            "canonical_present": True,
            "source_health_summary": {
                "total_sources": 2,
                "stale_count": 1,
                "sources": [
                    {"source": "benzinga_transcripts", "status": "HEALTHY", "freshness_seconds": 30.0, "stale": False},
                    {"source": "x_posts", "status": "DEGRADED", "freshness_seconds": 5400.0, "stale": True},
                ],
            },
        }
    )
    analysis_service.signal_data_hub.record_feature_bundle(
        ticker="NVDA",
        feature_bundle={
            "canonical_present": True,
            "coverage_pct": 71.43,
            "source_health_summary": {
                "total_sources": 2,
                "stale_count": 1,
                "sources": [
                    {"source": "benzinga_transcripts", "status": "HEALTHY", "freshness_seconds": 30.0, "stale": False},
                    {"source": "x_posts", "status": "DEGRADED", "freshness_seconds": 5400.0, "stale": True},
                ],
            },
        },
    )

    client = TestClient(main.app)
    response = client.get("/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_counts"] == {"economy": 1, "review": 1}
    assert payload["route_profile_counts"] == {"economy": 1, "review": 1}
    assert payload["llm_route_counts"] == {"gemini-3.1-flash-preview": 2, "gemini-3.1-pro-preview": 1}
    assert payload["avg_prompt_tokens"] == 270.0
    assert payload["avg_output_tokens"] == 58.5
    assert payload["cache_hit_rate"] == 0.5
    assert payload["coalesced_request_rate"] == 0.5
    assert payload["estimated_total_cost_usd"] == 0.0579
    assert payload["cost_per_approved_signal"] == 0.0579
    assert payload["flash_only_rate"] == 0.5
    assert payload["pro_escalation_rate"] == 0.5
    assert payload["prompt_budgets"]["economy"] == 384
    assert payload["route_usage"]["review"]["budget_tokens"] == 960
    assert payload["canonical_bundle_rate"] == 1.0
    assert payload["source_health_rate"] == 1.0
    assert payload["stale_source_rate"] == 1.0
    assert payload["source_health"]["sources"]["x_posts"]["degraded_rate"] == 1.0
    assert payload["datahub_topic_count"] == 3
    assert payload["signal_data_hub"]["by_domain"]["source_health"]["topics"] == 2
