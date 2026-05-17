from __future__ import annotations

from core.event_payload_builder import build_engine_event_response
from models.request_models import AnalyzeRequest, MarketData, SectionType, SourceType


def test_event_response_exposes_institutional_edge_card_and_brief_fields() -> None:
    payload = AnalyzeRequest(
        ticker="NVDA",
        prompt="Guidance improved and demand remained strong.",
        section_type=SectionType.GUIDANCE,
        source_type=SourceType.EARNINGS_CALL,
        chunk_sequence=1,
        market_data=MarketData(ticker="NVDA", current_price=100.0, volume_ratio=2.0),
    )
    analysis = {
        "direction": "BULLISH",
        "magnitude": 0.7,
        "confidence": 0.82,
        "rationale": "guidance improved",
        "catalyst_type": "GUIDANCE_UP",
        "strategy": "PEAD",
        "hold_days": 3,
        "risk_flags": [],
        "metadata": {
            "signal_explanation": {
                "summary_ko": "supported signal",
                "key_factors_ko": ["guidance improved"],
                "counterfactors_ko": [],
                "top_drivers": ["guidance improved"],
                "feature_contributions": [{"feature": "guidance", "direction": "positive", "magnitude": 0.8}],
            },
            "trade_plan": {
                "available": True,
                "entry_zone": [99.0, 101.0],
                "stop_loss": 96.0,
                "time_stop_days": 3,
            },
            "product_surface": {
                "schema_version": "2026-04-19.product-surface.v1",
                "actionability_score": 0.8,
                "recommended_primary_surface": "decision_unlock",
                "front_payload_ko": {
                    "primary_surface": {"code": "decision_unlock", "title": "Decision", "reason": "edge"},
                    "unlock_cards": [{"code": "decision_card", "title": "Decision"}],
                },
                "frontend_contract_ko": {"hero": {"title": "Long candidate"}},
                "institutional_edge": {
                    "schema_version": "2026-04-26.institutional-edge.v1",
                    "institutional_grade_score": 81.2,
                    "grade": "B",
                    "approval_state": "institutional_actionable",
                    "subscores": {"evidence_quality": 0.8},
                    "capacity": {"estimated_capacity_usd": 1500000.0},
                    "blockers": [],
                    "kill_conditions": ["invalidate_if_stop_loss_breached"],
                    "red_team": {"opposing_thesis": "priced in"},
                    "moat_vs_retail_ai": ["capacity_and_slippage_guard"],
                    "frontend": {"summary": "Institutional-ready signal package"},
                },
            },
            "institutional_edge": {
                "schema_version": "2026-04-26.institutional-edge.v1",
                "institutional_grade_score": 81.2,
                "grade": "B",
                "approval_state": "institutional_actionable",
                "subscores": {"evidence_quality": 0.8},
                "capacity": {"estimated_capacity_usd": 1500000.0},
                "blockers": [],
                "kill_conditions": ["invalidate_if_stop_loss_breached"],
                "red_team": {"opposing_thesis": "priced in"},
                "moat_vs_retail_ai": ["capacity_and_slippage_guard"],
                "frontend": {"summary": "Institutional-ready signal package"},
            },
        },
    }

    envelope = build_engine_event_response(payload=payload, analysis=analysis)

    assert envelope["signal_brief"]["institutional_approval_state"] == "institutional_actionable"
    assert envelope["signal_brief"]["institutional_grade"] == "B"
    assert envelope["data"]["analysis"]["institutional_edge"]["grade"] == "B"
    assert any(card["card_type"] == "institutional_edge" for card in envelope["data"]["cards"])
