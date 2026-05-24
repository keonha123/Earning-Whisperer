from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_earnings_intelligence_api_returns_fact_check_impact_and_risk_plan() -> None:
    app = main.create_app()
    app.state.analysis_service.external_retriever.reset_backend()
    app.state.analysis_service.external_retriever.clear()
    client = TestClient(app)

    response = client.post(
        "/v1/engine/earnings/intelligence",
        json={
            "ticker": "NVDA",
            "event_text": "Management raised guidance as AI demand remained strong and margins improved.",
            "question": "Can you quantify guidance and margin demand?",
            "answer": "We are focused on the long term and will share more to come.",
            "direction_hint": "BULLISH",
            "confidence_hint": 0.72,
            "market_data": {"ticker": "NVDA", "current_price": 900.0, "atr_pct_14": 0.035},
            "external_documents": [
                {
                    "doc_id": "filing-1",
                    "ticker": "NVDA",
                    "source_type": "filing",
                    "title": "8-K guidance",
                    "text": "NVIDIA raised full-year guidance after stronger AI demand and margin expansion.",
                    "importance": 0.95,
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "NVDA"
    assert payload["fact_checks"]
    assert payload["impact_chain"]
    assert payload["risk_plan"]["available"] is True
    assert payload["risk_plan"]["stop_loss"] is not None
    assert payload["omission_evasion"]["evasion_score"] > 0
