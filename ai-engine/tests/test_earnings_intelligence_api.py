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


def _node(chain: list[dict], ticker: str) -> dict:
    return next(item for item in chain if item["ticker"] == ticker)


def test_impact_score_reflects_co_mention_in_evidence_not_a_constant() -> None:
    """파급효과 점수는 근거 문서에 그 종목이 실제로 같이 등장하는 비율이어야 한다.

    이전 구현은 관계 문자열과 이벤트 문구만 보고 점수를 만들어서, 어떤 종목을 넣어도
    값이 똑같이 나왔다. 그 값은 측정이 아니라 상수였으므로 화면에 띄울 의미가 없었다.
    """
    app = main.create_app()
    app.state.analysis_service.external_retriever.reset_backend()
    app.state.analysis_service.external_retriever.clear()
    client = TestClient(app)

    # TGT 는 두 문서 모두에, COST 는 어디에도 등장하지 않는다.
    documents = [
        {
            "doc_id": "news-1",
            "ticker": "WMT",
            "source_type": "news",
            "title": "Walmart raises guidance",
            "text": "Walmart raised guidance as grocery demand stayed strong, pressuring TGT on price.",
            "importance": 0.9,
        },
        {
            "doc_id": "news-2",
            "ticker": "WMT",
            "source_type": "news",
            "title": "Retail price war",
            "text": "Analysts said TGT would have to answer Walmart's rollbacks in the coming quarter.",
            "importance": 0.9,
        },
    ]

    response = client.post(
        "/v1/engine/earnings/intelligence",
        json={
            "ticker": "WMT",
            "event_text": "Comp sales grew and we invested the tariff refunds back into price.",
            "related_tickers": ["TGT", "COST"],
            "external_documents": documents,
        },
    )

    assert response.status_code == 200
    chain = response.json()["impact_chain"]

    tgt = _node(chain, "TGT")
    cost = _node(chain, "COST")
    assert tgt["impact_score"] > cost["impact_score"], "종목마다 값이 달라야 한다"
    assert cost["impact_score"] == 0.0
    assert "TGT" in tgt["rationale_ko"]


def test_impact_score_is_null_when_there_is_no_evidence_corpus() -> None:
    """근거가 하나도 없으면 0.0 이 아니라 미측정(None)으로 내려보낸다.

    0.0 은 "영향 없음" 으로 읽히지만 실제로는 "잴 것이 없었다" 이다. 둘을 같은 값으로
    내려보내면 근거 적재를 빠뜨린 것을 화면에서 알아챌 수 없다.
    """
    app = main.create_app()
    app.state.analysis_service.external_retriever.reset_backend()
    app.state.analysis_service.external_retriever.clear()
    client = TestClient(app)

    response = client.post(
        "/v1/engine/earnings/intelligence",
        json={
            "ticker": "WMT",
            "event_text": "Comp sales grew this quarter.",
            "related_tickers": ["TGT"],
            "external_documents": [],
        },
    )

    assert response.status_code == 200
    chain = response.json()["impact_chain"]
    assert chain
    assert all(item["impact_score"] is None for item in chain)
    assert all(item["confidence"] == 0.0 for item in chain)
