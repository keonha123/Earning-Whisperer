from datetime import UTC, datetime
import asyncio

from models.evidence_models import EvidenceDocument, EvidenceSourceType
from models.ingestion_models import EarningsTranscriptIngestItem, TranscriptSpeakerTurn
from repositories.evidence_store_repository import EvidenceStoreRepository
from services.transcript_ingestion_service import TranscriptIngestionService
from services.transcript_diff_service import TranscriptDiffService
from models.request_models import SourceType


def test_sparse_latest_requires_known_date_prior_ticker_and_call_type():
    repo = EvidenceStoreRepository(documents=[
        EvidenceDocument(document_id=key, ticker=ticker, source_type=kind,
                         published_at=published, content="Revenue guidance")
        for key, ticker, kind, published in [
            ("old", "WMT", EvidenceSourceType.EARNINGS_CALL, "2025-01-01"),
            ("latest", "WMT", EvidenceSourceType.EARNINGS_CALL, "2025-04-01"),
            ("current", "WMT", EvidenceSourceType.EARNINGS_CALL, "2025-07-01"),
            ("future", "WMT", EvidenceSourceType.EARNINGS_CALL, "2025-10-01"),
            ("unknown", "WMT", EvidenceSourceType.EARNINGS_CALL, None),
            ("other-ticker", "NVDA", EvidenceSourceType.EARNINGS_CALL, "2025-06-01"),
            ("news", "WMT", EvidenceSourceType.NEWS, "2025-06-01"),
        ]
    ])
    assert repo.find_latest_transcript(ticker="wmt", before=datetime(2025, 7, 1, tzinfo=UTC))["document_id"] == "latest"
    assert repo.find_latest_transcript(ticker="MSFT") is None


def test_sparse_ingestion_retrieves_tail_turn_and_replaces_old_content():
    repo = EvidenceStoreRepository()
    service = TranscriptIngestionService(repo)
    turns = [TranscriptSpeakerTurn(speaker="Operator", text=f"Welcome participant {index}") for index in range(90)]
    turns.append(TranscriptSpeakerTurn(speaker="CFO", text="Revenue guidance increased with stronger margins."))
    item = EarningsTranscriptIngestItem(provider="test", provider_id="q1", ticker="WMT", title="Q1",
                                       content="Entire call", published_at="2025-04-01T00:00:00Z", speaker_turns=turns)
    result = service.ingest([item])
    assert result.accepted_count == 1
    hits = repo.search_prior_transcript_chunks(ticker="WMT", query="revenue guidance margins",
                                              document_id=result.document_ids[0])
    assert hits and hits[0].metadata["turn_index"] == 90
    assert hits[0].metadata["speaker"] == "CFO"
    assert hits[0].metadata["retrieval_backend"] == "LOCAL_SPARSE"
    assert "speaker_turns" not in hits[0].metadata
    diff_service = TranscriptDiffService(repo)

    async def offline_diff(**kwargs):
        raise RuntimeError("No LLM in this storage test")

    diff_service._generate_llm_diff = offline_diff
    diff = asyncio.run(diff_service.analyze(ticker="WMT", current_chunk="Revenue guidance increased with stronger margins.",
                       source_type=SourceType.EARNINGS_CALL, request_metadata={"timestamp": "2025-07-01T00:00:00Z"}))
    assert diff["available"] is True
    assert diff["previous_document"]["document_id"] == result.document_ids[0]
    assert "transcript_repository_not_configured" not in diff["warnings"]
    assert repo.search_prior_transcript_chunks(ticker="NVDA", query="revenue", document_id=result.document_ids[0]) == []
    service.ingest([item.model_copy(update={"speaker_turns": turns[:1]})])
    assert repo.search_prior_transcript_chunks(ticker="WMT", query="revenue guidance margins",
                                             document_id=result.document_ids[0]) == []
