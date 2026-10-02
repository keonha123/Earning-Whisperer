import asyncio
from types import SimpleNamespace

import pytest

from models.evidence_models import EvidenceCitation, EvidenceSourceType
from models.request_models import SourceType
from services.transcript_diff_service import TranscriptDiffService, _normalize_llm_items, _metadata_timestamp


def citation():
    return EvidenceCitation(document_id="prior", ticker="WMT", source_type=EvidenceSourceType.EARNINGS_CALL,
        source="IR", snippet="We reiterate our full year sales guidance of 3.5% to 4.5%.",
        relevance_score=0.9, reliability_score=0.88, confidence_score=0.88)


def item():
    return {"current_claim": "We raise sales guidance to 4% to 5%.",
        "prior_claim": "We reiterate our full year sales guidance of 3.5% to 4.5%.",
        "summary_ko": "매출 가이던스 범위가 상향되었습니다.", "change_type": "improved", "evidence_indices": [1]}


@pytest.mark.parametrize("indices", [[0], [-1], [2], [True], [1.5], ["1"], None])
def test_diff_rejects_invalid_citation_references(indices):
    raw = item() | {"evidence_indices": indices}
    assert _normalize_llm_items([raw], [citation()], current_chunk=item()["current_claim"]) == []


@pytest.mark.parametrize("field", ["current_claim", "prior_claim"])
def test_diff_rejects_model_invented_claims(field):
    raw = item() | {field: "We doubled earnings to 999 billion dollars."}
    assert _normalize_llm_items([raw], [citation()], current_chunk=item()["current_claim"]) == []


def test_diff_preserves_grounded_excerpt():
    assert len(_normalize_llm_items([item()], [citation()], current_chunk=item()["current_claim"])) == 1


def test_diff_timestamp_does_not_silently_use_today_for_replay():
    assert _metadata_timestamp({"timestamp": "2026-05-21T12:00:00Z"}).year == 2026
    assert _metadata_timestamp({"timestamp": 1_779_364_800}).tzinfo is not None
    with pytest.raises(ValueError):
        _metadata_timestamp({"timestamp": "not-a-date"})



@pytest.mark.asyncio
async def test_transcript_diff_llm_timeout_returns_bounded_fallback(monkeypatch):
    class Repository:
        def find_latest_transcript(self, **kwargs):
            return {"document_id": "prior"}
        def search_prior_transcript_chunks(self, **kwargs):
            return [citation()]
    service = TranscriptDiffService(Repository())
    async def slow(**kwargs):
        await asyncio.sleep(10)
    monkeypatch.setattr(service, "_generate_llm_diff", slow)
    monkeypatch.setattr("services.transcript_diff_service.get_settings", lambda: SimpleNamespace(
        transcript_diff_retrieval_timeout_seconds=1, transcript_diff_llm_timeout_seconds=0.01))
    response = await service.analyze(ticker="WMT", current_chunk="We raise sales guidance to 4% to 5% for the full year.",
        source_type=SourceType.EARNINGS_CALL)
    assert response["items"][0]["prior_claim"] == citation().snippet
    assert "historical_transcript_diff_llm_failed" in response["warnings"]


@pytest.mark.asyncio
async def test_transcript_repository_failure_is_explicit_unavailable():
    class Repository:
        def find_latest_transcript(self, **kwargs):
            raise ConnectionError("private connection detail")
        def search_prior_transcript_chunks(self, **kwargs):
            raise AssertionError("not reached")
    response = await TranscriptDiffService(Repository()).analyze(ticker="WMT", current_chunk="Revenue guidance",
        source_type=SourceType.EARNINGS_CALL)
    assert response["available"] is False
    assert response["warnings"] == ["transcript_retrieval_failed"]
