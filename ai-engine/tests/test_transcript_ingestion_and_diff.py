from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import main
from core.analysis_service import AnalysisService
from core.gemini_client import GenerationUsage
from models.evidence_models import EvidenceCitation, EvidenceSourceType
from models.ingestion_models import EarningsTranscriptIngestItem
from models.request_models import MarketData, SectionType, SourceType
from services.transcript_diff_service import TranscriptDiffService
from services.transcript_ingestion_service import TranscriptIngestionService


class FakeTranscriptRepository:
    def __init__(self, *, previous=True, citation_score=0.91, citation_confidence=0.90) -> None:
        self.documents = []
        self.previous = previous
        self.citation_score = citation_score
        self.citation_confidence = citation_confidence

    def add_documents(self, documents):
        self.documents.extend(documents)
        return len(documents)

    def find_latest_transcript(self, **kwargs):
        if not self.previous:
            return None
        return {
            "document_id": "investing:NVDA:prev",
            "title": "NVDA Q2 transcript",
            "published_at": "2025-08-01",
            "fiscal_quarter": "Q2_2025",
            "source_url": "https://www.investing.com/news/transcripts/example",
        }

    def search_prior_transcript_chunks(self, **kwargs):
        return [
            EvidenceCitation(
                document_id="investing:NVDA:prev",
                ticker="NVDA",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="investing",
                title="NVDA Q2 transcript",
                published_at="2025-08-01",
                source_url="https://www.investing.com/news/transcripts/example",
                snippet="Guidance was lowered and demand slowed in the prior quarter.",
                relevance_score=self.citation_score,
                reliability_score=0.88,
                confidence_score=self.citation_confidence,
            )
        ]


def test_transcript_ingestion_maps_payload_to_evidence_document() -> None:
    repository = FakeTranscriptRepository()
    service = TranscriptIngestionService(repository)
    response = service.ingest(
        [
            EarningsTranscriptIngestItem(
                provider="investing",
                provider_id="123",
                ticker="nvda",
                title="Earnings call transcript: NVIDIA Q3 2025",
                published_at=1_700_000_000,
                fiscal_quarter="Q3_2025",
                content="Full transcript. Guidance improved and AI demand remained strong.",
            )
        ]
    )

    assert response.accepted_count == 1
    assert repository.documents[0].document_id == "investing:NVDA:123"
    assert repository.documents[0].source_type == EvidenceSourceType.EARNINGS_CALL
    assert repository.documents[0].source_url is None
    assert repository.documents[0].metadata["fiscal_quarter"] == "Q3_2025"


@pytest.mark.asyncio
async def test_transcript_diff_returns_llm_change_summary_against_prior_call(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_generate_content_with_metadata(**kwargs):
        calls["count"] += 1
        return GenerationUsage(
            text=json.dumps(
                {
                    "items": [
                        {
                            "topic": "demand",
                            "change_type": "improved",
                            "summary_ko": "Prior demand language weakened, while the current chunk shows improvement.",
                            "current_claim": "AI demand accelerated.",
                            "prior_claim": "Demand slowed in the prior quarter.",
                            "confidence": 0.84,
                            "risk_score": 0.22,
                            "evidence_indices": [1],
                        }
                    ]
                }
            ),
            prompt_tokens=100,
            output_tokens=50,
            total_tokens=150,
        )

    monkeypatch.setattr("services.transcript_diff_service.gemini_client.generate_content_with_metadata", _fake_generate_content_with_metadata)
    service = TranscriptDiffService(FakeTranscriptRepository())
    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Guidance improved as AI demand accelerated and margins expanded.",
        source_type=SourceType.EARNINGS_CALL,
        request_metadata={},
    )

    assert result is not None
    assert result["available"] is True
    assert result["previous_document"]["document_id"] == "investing:NVDA:prev"
    assert result["items"]
    assert result["items"][0]["change_type"] == "improved"
    assert result["items"][0]["evidence"]
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_transcript_diff_does_not_call_llm_without_prior_transcript(monkeypatch) -> None:
    async def _fail_if_called(**kwargs):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr("services.transcript_diff_service.gemini_client.generate_content_with_metadata", _fail_if_called)
    service = TranscriptDiffService(FakeTranscriptRepository(previous=False))

    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Guidance improved as AI demand accelerated and margins expanded.",
        source_type=SourceType.EARNINGS_CALL,
        request_metadata={},
    )

    assert result is not None
    assert result["available"] is False
    assert result["warnings"] == ["previous_transcript_not_found"]


@pytest.mark.asyncio
async def test_transcript_diff_gates_out_weak_prior_evidence(monkeypatch) -> None:
    async def _fail_if_called(**kwargs):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr("services.transcript_diff_service.gemini_client.generate_content_with_metadata", _fail_if_called)
    service = TranscriptDiffService(FakeTranscriptRepository(citation_score=0.42, citation_confidence=0.55))

    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Guidance improved as AI demand accelerated and margins expanded.",
        source_type=SourceType.EARNINGS_CALL,
        request_metadata={},
    )

    assert result is not None
    assert result["available"] is True
    assert result["items"] == []
    assert "weak_prior_transcript_evidence" in result["warnings"]


@pytest.mark.asyncio
async def test_transcript_diff_falls_back_when_llm_returns_invalid_json(monkeypatch) -> None:
    async def _invalid_generate_content_with_metadata(**kwargs):
        return GenerationUsage(text="not json", prompt_tokens=1, output_tokens=1, total_tokens=2)

    monkeypatch.setattr("services.transcript_diff_service.gemini_client.generate_content_with_metadata", _invalid_generate_content_with_metadata)
    service = TranscriptDiffService(FakeTranscriptRepository())

    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Guidance improved as AI demand accelerated and margins expanded.",
        source_type=SourceType.EARNINGS_CALL,
        request_metadata={},
    )

    assert result is not None
    assert result["items"]
    assert result["items"][0]["change_type"] == "improved"
    assert "historical_transcript_diff_llm_failed" in result["warnings"]


@pytest.mark.asyncio
async def test_analysis_service_does_not_attach_historical_transcript_diff_metadata(monkeypatch) -> None:
    async def _fake_generate_content_with_metadata(*, model, contents=None, prompt=None, config):
        return GenerationUsage(
            text=json.dumps(
                {
                    "direction": "BULLISH",
                    "magnitude": 0.5,
                    "confidence": 0.75,
                    "rationale": "Demand and guidance improved.",
                    "catalyst_type": "GUIDANCE_RAISE",
                    "euphemism_count": 0,
                    "negative_word_ratio": 0.0,
                }
            )
        )

    monkeypatch.setattr("core.analysis_service.gemini_client.generate_content_with_metadata", _fake_generate_content_with_metadata)
    service = AnalysisService(transcript_diff_service=TranscriptDiffService(FakeTranscriptRepository()))

    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Guidance improved as AI demand accelerated and margins expanded.",
        market_data=MarketData(ticker="NVDA", current_price=900.0, volume_ratio=2.0),
        section_type=SectionType.GUIDANCE,
        source_type=SourceType.EARNINGS_CALL,
        chunk_sequence=1,
        request_priority=8,
        is_final=False,
        request_metadata={},
    )

    assert "historical_transcript_diff" not in result.metadata


def test_transcript_diff_endpoint_runs_independently_from_main_analysis(monkeypatch) -> None:
    async def _fake_generate_content_with_metadata(**kwargs):
        return GenerationUsage(
            text=json.dumps(
                {
                    "items": [
                        {
                            "topic": "demand",
                            "change_type": "improved",
                            "summary_ko": "Prior demand language weakened, while the current chunk shows improvement.",
                            "current_claim": "AI demand accelerated.",
                            "prior_claim": "Demand slowed in the prior quarter.",
                            "confidence": 0.84,
                            "risk_score": 0.22,
                            "evidence_indices": [1],
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr("services.transcript_diff_service.gemini_client.generate_content_with_metadata", _fake_generate_content_with_metadata)
    app = main.create_app()
    app.state.transcript_diff_service = TranscriptDiffService(FakeTranscriptRepository())
    client = TestClient(app)

    response = client.post(
        "/v1/engine/transcript/diff",
        json={
            "ticker": "NVDA",
            "current_chunk": "Guidance improved as AI demand accelerated and margins expanded.",
            "request_metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["items"][0]["change_type"] == "improved"
