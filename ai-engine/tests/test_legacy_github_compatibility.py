from __future__ import annotations

from fastapi.testclient import TestClient

import main
from models.legacy_contract_models import LegacyPublishResult
from models.request_models import SectionType, SourceType
from models.signal_models import GeminiAnalysisResult


async def _fake_analyze(**kwargs):
    assert kwargs["ticker"] == "TSLA"
    assert kwargs["current_chunk"] == "Margins compressed and demand was softer than expected."
    assert kwargs["chunk_sequence"] == 7
    assert kwargs["section_type"] == SectionType.UNKNOWN
    assert kwargs["source_type"] == SourceType.EARNINGS_CALL
    return GeminiAnalysisResult(
        direction="BEARISH",
        magnitude=0.62,
        confidence=0.81,
        rationale="Demand softened and margin pressure increased.",
        catalyst_type="DEMAND_DOWN",
        strategy="REVERSAL_CATALYST",
        hold_days=2,
        metadata={"signal_explanation": {"summary_ko": "Demand and margins weakened."}},
    )


class _FakePublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.legacy_signal = None
        self.enriched_message = None

    async def publish(self, *, legacy_signal, enriched_message=None):
        self.legacy_signal = legacy_signal
        self.enriched_message = enriched_message
        if self.fail:
            return LegacyPublishResult(legacy_published=False, enriched_published=False, error="legacy:redis down")
        return LegacyPublishResult(legacy_published=True, enriched_published=True)


def test_legacy_analyze_endpoint_accepts_original_payload_and_publishes(monkeypatch) -> None:
    publisher = _FakePublisher()
    monkeypatch.setattr(main.app.state.analysis_service, "analyze", _fake_analyze)
    monkeypatch.setattr(main.app.state, "redis_signal_publisher", publisher)
    client = TestClient(main.app)

    response = client.post(
        "/api/v1/analyze",
        json={
            "ticker": "TSLA",
            "text_chunk": "Margins compressed and demand was softer than expected.",
            "sequence": 7,
            "timestamp": 1778600000,
            "is_final": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "TSLA"
    assert payload["raw_score"] == -0.62
    assert payload["ai_score"] == -0.62
    assert payload["rationale"] == "Demand softened and margin pressure increased."
    assert payload["text_chunk"] == "Margins compressed and demand was softer than expected."
    assert payload["timestamp"] == 1778600000
    assert payload["is_session_end"] is False
    assert payload["redis_published"] is True
    assert payload["enriched_published"] is True
    assert payload["engine_envelope"]["request_metadata"]["original_timestamp"] == 1778600000
    assert publisher.legacy_signal.raw_score == -0.62
    assert publisher.legacy_signal.ai_score == -0.62
    assert publisher.enriched_message["legacy_signal"]["ticker"] == "TSLA"


def test_legacy_analyze_endpoint_degrades_when_redis_publish_fails(monkeypatch) -> None:
    publisher = _FakePublisher(fail=True)
    monkeypatch.setattr(main.app.state.analysis_service, "analyze", _fake_analyze)
    monkeypatch.setattr(main.app.state, "redis_signal_publisher", publisher)
    client = TestClient(main.app)

    response = client.post(
        "/api/v1/analyze",
        json={
            "ticker": "TSLA",
            "text_chunk": "Margins compressed and demand was softer than expected.",
            "sequence": 7,
            "timestamp": 1778600000,
            "is_final": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["redis_published"] is False
    assert payload["enriched_published"] is False
    assert payload["publish_error"] == "legacy:redis down"
    assert payload["is_session_end"] is True
