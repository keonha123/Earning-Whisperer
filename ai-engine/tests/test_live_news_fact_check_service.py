from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from config import Settings
from core.external_retriever import ExternalRetrievedDocument
from models.live_fact_check_models import LiveFactCheckSentenceRequest
from services.live_news_fact_check_service import LiveNewsFactCheckService


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


class FakeRetriever:
    def __init__(self, batches=None, error: Exception | None = None) -> None:
        self.batches = list(batches or [])
        self.error = error
        self.calls = []

    def retrieve_many(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.batches


class FakeLlmClient:
    def __init__(self, *payloads) -> None:
        self.payloads = list(payloads)
        self.calls = []

    async def generate_content_with_metadata(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(text=text)


def _settings() -> Settings:
    return Settings(
        VECTOR_STORE_BACKEND="memory",
        FACT_CHECK_RETRIEVAL_TIMEOUT_SECONDS=2.0,
        FACT_CHECK_LLM_TIMEOUT_SECONDS=2.0,
        FACT_CHECK_EXTRACTION_TIMEOUT_SECONDS=2.0,
        FACT_CHECK_SENTENCE_BUFFER_TTL_SECONDS=10,
        FACT_CHECK_ENDED_CALL_TTL_SECONDS=20,
    )


def _request(sequence: int, *, ticker: str = "NVDA", end: bool = False, sentence: str | None = None):
    texts = [
        "Data center revenue increased twenty percent year over year.",
        "Gross margin expanded to seventy five percent.",
        "The company launched its new accelerator in March.",
        "Gaming revenue remained flat year over year.",
    ]
    return LiveFactCheckSentenceRequest(
        ticker=ticker,
        sentence=sentence or texts[sequence % len(texts)],
        sentence_sequence=sequence,
        sentence_timestamp=1_900_000_000 + sequence,
        is_session_end=end,
    )


def _document(doc_id: str, *, score: float = 0.45, source: str = "Reuters") -> ExternalRetrievedDocument:
    return ExternalRetrievedDocument(
        doc_id=doc_id,
        title=f"News {doc_id}",
        text="NVIDIA data center revenue increased and gross margin expanded.",
        score=score,
        semantic_score=score,
        published_at=1_899_999_000,
        source_type="news",
        url=f"https://{source.lower().replace(' ', '')}.example/{doc_id}",
        metadata={"source": source},
    )


def _extraction_two_claims():
    return {
        "claims": [
            {
                "sentence_index": 0,
                "source_text": "Data center revenue increased twenty percent year over year.",
                "normalized_claim": "Data center revenue increased 20% year over year.",
                "claim_type": "numeric_fact",
            },
            {
                "sentence_index": 1,
                "source_text": "Gross margin expanded to seventy five percent.",
                "normalized_claim": "Gross margin expanded to 75%.",
                "claim_type": "numeric_fact",
            },
        ],
        "excluded_count": 1,
    }


@pytest.mark.asyncio
async def test_first_two_sentences_buffer_and_third_runs_pipeline() -> None:
    retriever = FakeRetriever([[_document("a")], [_document("b")]])
    llm = FakeLlmClient(
        _extraction_two_claims(),
        {
            "results": [
                {"claim_id": "NVDA:0-2:c1", "verdict": "SUPPORTED", "confidence": 0.9, "explanation_ko": "뉴스가 매출 증가를 뒷받침합니다.", "evidence_indices": [1]},
                {"claim_id": "NVDA:0-2:c2", "verdict": "SUPPORTED", "confidence": 0.85, "explanation_ko": "뉴스가 마진 확대를 뒷받침합니다.", "evidence_indices": [1]},
            ]
        },
    )
    service = LiveNewsFactCheckService(retriever=retriever, llm_client=llm, settings=_settings())

    first = await service.submit_sentence(_request(0))
    second = await service.submit_sentence(_request(1))
    third = await service.submit_sentence(_request(2))

    assert first.status == "BUFFERING" and first.buffered_count == 1
    assert second.status == "BUFFERING" and second.buffered_count == 2
    assert third.status == "COMPLETED"
    assert len(third.claims) == 2
    assert len(llm.calls) == 2
    assert len(retriever.calls) == 1
    assert retriever.calls[0]["queries"] == ["Data center revenue increased 20% year over year.", "Gross margin expanded to 75%."]
    assert retriever.calls[0]["chunk_timestamps"] == [1_900_000_000, 1_900_000_001]
    assert retriever.calls[0]["semantic_only"] is True
    assert third.excluded_count == 1


@pytest.mark.asyncio
async def test_verification_accepts_top_level_list_and_confidence_labels() -> None:
    retriever = FakeRetriever([[_document("a")], [_document("b")]])
    llm = FakeLlmClient(
        _extraction_two_claims(),
        [
            {"claim_id": "NVDA:0-2:c1", "verdict": "SUPPORTED", "confidence": "HIGH", "explanation_ko": "뉴스가 매출 증가를 뒷받침합니다.", "evidence_indices": [1]},
            {"claim_id": "NVDA:0-2:c2", "verdict": "INSUFFICIENT_EVIDENCE", "confidence": "MEDIUM", "explanation_ko": "뉴스 근거가 구체적이지 않습니다.", "evidence_indices": [], "insufficient_reason": None},
        ],
    )
    service = LiveNewsFactCheckService(retriever=retriever, llm_client=llm, settings=_settings())

    for sequence in range(2):
        await service.submit_sentence(_request(sequence))
    result = await service.submit_sentence(_request(2))

    assert result.warnings == []
    assert result.claims[0].verdict == "SUPPORTED"
    assert result.claims[0].confidence == 0.85
    assert result.claims[1].verdict == "INSUFFICIENT_EVIDENCE"
    assert result.claims[1].confidence == 0.6


@pytest.mark.asyncio
async def test_fourth_sentence_starts_a_new_batch() -> None:
    llm = FakeLlmClient({"claims": [], "excluded_count": 3})
    service = LiveNewsFactCheckService(retriever=FakeRetriever(), llm_client=llm, settings=_settings())
    for sequence in range(3):
        await service.submit_sentence(_request(sequence))

    fourth = await service.submit_sentence(_request(3))

    assert fourth.status == "BUFFERING"
    assert fourth.buffered_count == 1


@pytest.mark.asyncio
async def test_session_end_discards_partial_batch_and_allows_new_sequence_zero_session() -> None:
    llm = FakeLlmClient()
    service = LiveNewsFactCheckService(retriever=FakeRetriever(), llm_client=llm, settings=_settings())

    await service.submit_sentence(_request(0))
    ended = await service.submit_sentence(_request(1, end=True))
    followup = await service.submit_sentence(_request(0))

    assert ended.status == "DISCARDED"
    assert ended.warnings == ["partial_batch_discarded"]
    assert followup.status == "BUFFERING"
    assert followup.buffered_count == 1
    assert not llm.calls


@pytest.mark.asyncio
async def test_sequence_guards_preserve_buffer() -> None:
    service = LiveNewsFactCheckService(retriever=FakeRetriever(), llm_client=FakeLlmClient(), settings=_settings())

    first = await service.submit_sentence(_request(5))
    duplicate = await service.submit_sentence(_request(5))
    gap = await service.submit_sentence(_request(7))

    assert first.status == "BUFFERING"
    assert duplicate.status == "REJECTED"
    assert "duplicate_or_regressed_sequence" in duplicate.warnings
    assert gap.status == "BUFFERING"
    assert "sequence_gap" in gap.warnings


@pytest.mark.asyncio
async def test_buffers_are_isolated_by_ticker() -> None:
    service = LiveNewsFactCheckService(retriever=FakeRetriever(), llm_client=FakeLlmClient(), settings=_settings())

    first_a = await service.submit_sentence(_request(0, ticker="NVDA"))
    first_b = await service.submit_sentence(_request(0, ticker="AMD"))
    second_a = await service.submit_sentence(_request(1, ticker="NVDA"))

    assert first_a.buffered_count == 1
    assert first_b.buffered_count == 1
    assert second_a.buffered_count == 2


@pytest.mark.asyncio
async def test_expired_partial_buffer_starts_fresh() -> None:
    clock = FakeClock()
    service = LiveNewsFactCheckService(retriever=FakeRetriever(), llm_client=FakeLlmClient(), settings=_settings(), clock=clock)

    await service.submit_sentence(_request(0))
    clock.value += 11
    result = await service.submit_sentence(_request(1))

    assert result.status == "BUFFERING"
    assert result.buffered_count == 1
    assert "buffer_expired" in result.warnings


@pytest.mark.asyncio
async def test_sequence_zero_resets_existing_ticker_buffer() -> None:
    service = LiveNewsFactCheckService(retriever=FakeRetriever(), llm_client=FakeLlmClient(), settings=_settings())
    await service.submit_sentence(_request(0))
    await service.submit_sentence(_request(1))

    reset = await service.submit_sentence(_request(0))

    assert reset.status == "BUFFERING"
    assert reset.buffered_count == 1
    assert "buffer_reset_on_sequence_zero" in reset.warnings


@pytest.mark.asyncio
async def test_no_relevant_news_skips_verification_llm() -> None:
    llm = FakeLlmClient(_extraction_two_claims())
    retriever = FakeRetriever([[], []])
    service = LiveNewsFactCheckService(retriever=retriever, llm_client=llm, settings=_settings())

    for sequence in range(2):
        await service.submit_sentence(_request(sequence))
    result = await service.submit_sentence(_request(2))

    assert result.status == "COMPLETED"
    assert len(result.claims) == 2
    assert all(item.verdict == "INSUFFICIENT_EVIDENCE" for item in result.claims)
    assert all(item.reason_code == "insufficient_relevance" for item in result.claims)
    assert len(llm.calls) == 1
    assert result.verification_llm_used is False


@pytest.mark.asyncio
async def test_claim_limits_source_validation_and_deduplication() -> None:
    sentence = "Revenue increased and margin expanded."
    extraction = {
        "claims": [
            {"sentence_index": 0, "source_text": "Revenue increased", "normalized_claim": "Revenue increased.", "claim_type": "current_fact"},
            {"sentence_index": 0, "source_text": "margin expanded", "normalized_claim": "Margin expanded.", "claim_type": "current_fact"},
            {"sentence_index": 0, "source_text": "Revenue increased", "normalized_claim": "Revenue increased.", "claim_type": "current_fact"},
            {"sentence_index": 0, "source_text": "not in source", "normalized_claim": "Inventory declined.", "claim_type": "current_fact"},
            {"sentence_index": 1, "source_text": "Gross margin expanded", "normalized_claim": "Forecast will improve.", "claim_type": "forecast"},
        ],
        "excluded_count": 0,
    }
    llm = FakeLlmClient(extraction)
    service = LiveNewsFactCheckService(retriever=FakeRetriever([[], []]), llm_client=llm, settings=_settings())
    await service.submit_sentence(_request(0, sentence=sentence))
    await service.submit_sentence(_request(1))
    result = await service.submit_sentence(_request(2))

    assert len(result.claims) == 2
    assert result.excluded_count == 3
    assert "invalid_or_duplicate_claims_discarded" in result.warnings


@pytest.mark.asyncio
async def test_invalid_verdict_is_isolated_to_its_claim() -> None:
    retriever = FakeRetriever([[_document("a")], [_document("b")]])
    llm = FakeLlmClient(
        _extraction_two_claims(),
        {
            "results": [
                {"claim_id": "NVDA:0-2:c1", "verdict": "SUPPORTED", "confidence": 0.9, "explanation_ko": "뉴스가 매출 증가를 뒷받침합니다.", "evidence_indices": [1]},
                {"claim_id": "NVDA:0-2:c2", "verdict": "SUPPORTED", "confidence": 0.8, "explanation_ko": "잘못된 인용입니다.", "evidence_indices": [9]},
            ]
        },
    )
    service = LiveNewsFactCheckService(retriever=retriever, llm_client=llm, settings=_settings())
    for sequence in range(2):
        await service.submit_sentence(_request(sequence))
    result = await service.submit_sentence(_request(2))

    assert result.claims[0].verdict == "SUPPORTED"
    assert result.claims[1].verdict == "INSUFFICIENT_EVIDENCE"
    assert result.claims[1].reason_code == "invalid_llm_response"
    assert "invalid_or_missing_claim_verdicts" in result.warnings


@pytest.mark.asyncio
async def test_batch_retrieval_failure_marks_each_claim() -> None:
    service = LiveNewsFactCheckService(
        retriever=FakeRetriever(error=RuntimeError("qdrant unavailable")),
        llm_client=FakeLlmClient(_extraction_two_claims()),
        settings=_settings(),
    )
    for sequence in range(2):
        await service.submit_sentence(_request(sequence))
    result = await service.submit_sentence(_request(2))

    assert all(item.reason_code == "retrieval_failed" for item in result.claims)
    assert "claim_retrieval_failed" in result.warnings
    assert result.verification_llm_used is False
