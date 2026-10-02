from datetime import UTC, datetime

import pytest
from qdrant_client import QdrantClient, models

from config import Settings
from core.external_retriever import HashEmbeddingProvider
from models.evidence_models import EvidenceDocument, EvidenceSourceType
from models.ingestion_models import EarningsTranscriptIngestItem, TranscriptSpeakerTurn
from repositories.qdrant_evidence_repository import QdrantEvidenceRepository
from services.transcript_ingestion_service import TranscriptIngestionService


@pytest.fixture
def repo():
    client = QdrantClient(":memory:")
    repository = QdrantEvidenceRepository(
        client=client, store_name="transcript", collection_name="transcripts",
        embedding_provider=HashEmbeddingProvider(dimension=64), embedding_dimension=64,
        chunk_size_chars=600, chunk_overlap_chars=80,
    )
    yield repository
    client.close()


def test_every_speaker_turn_is_searchable_and_not_duplicated_in_payload(repo):
    turns = [TranscriptSpeakerTurn(speaker="CEO", text=f"Prepared statement number {i} about operations") for i in range(100)]
    turns.append(TranscriptSpeakerTurn(speaker="CFO", text="Zebra aurora forecast unique closing marker"))
    item = EarningsTranscriptIngestItem(provider_id="call1", ticker="WMT", title="Call",
        content=" ".join(t.text for t in turns), speaker_turns=turns)
    result = TranscriptIngestionService(repo).ingest([item])
    points = repo._scroll(filters=[], limit=25)
    assert result.accepted_count == 1
    assert len(points) == 101
    assert all("speaker_turns" not in p.payload for p in points)
    matches = repo.search_prior_transcript_chunks(ticker="WMT", document_id=result.document_ids[0],
        query=turns[-1].text, top_k=1)
    assert matches[0].snippet == turns[-1].text
    assert matches[0].metadata["speaker"] == "CFO"


def test_replacing_transcript_removes_old_tail_only_after_success(repo):
    original = EvidenceDocument(document_id="call", ticker="WMT", source_type=EvidenceSourceType.EARNINGS_CALL,
        source="test", content="Legacy long section. " * 120)
    repo.add_documents([original])
    assert repo.client.count(collection_name="transcripts").count > 1
    original_embed = repo.embedding_provider.embed_texts
    repo.embedding_provider.embed_texts = lambda texts: []
    with pytest.raises(RuntimeError, match="response count"):
        repo.add_documents([original.model_copy(update={"content": "Corrected short section."})])
    assert repo.client.count(collection_name="transcripts").count > 1
    repo.embedding_provider.embed_texts = original_embed
    repo.add_documents([original.model_copy(update={"content": "Corrected short section."})])
    points = repo._scroll(filters=[], limit=25)
    assert len(points) == 1
    assert points[0].payload["chunk_text"] == "Corrected short section."


def test_find_latest_checks_pages_after_first_256_points(repo):
    # Integer point IDs guarantee the newest prior call is outside page one.
    points = [models.PointStruct(id=i, vector=[1.0] + [0.0] * 63, payload={
        "store": "transcript", "ticker": "WMT", "source_type": "EARNINGS_CALL",
        "embedding_version": repo.embedding_version, "document_id": f"call-{i}",
        "published_at_epoch": i + 1, "chunk_text": "Prior guidance",
    }) for i in range(300)]
    repo.client.upsert(collection_name="transcripts", points=points)
    latest = repo.find_latest_transcript(ticker="WMT", before=datetime(2026, 1, 1, tzinfo=UTC))
    assert latest["document_id"] == "call-299"


def test_duplicate_revision_in_one_batch_does_not_keep_old_tail(repo):
    original = EvidenceDocument(document_id="call", ticker="WMT", source_type=EvidenceSourceType.EARNINGS_CALL,
        source="test", content="Obsolete long section. " * 120)
    accepted = repo.add_documents([original, original.model_copy(update={"content": "Last revision."})])
    assert accepted == 1
    points = repo._scroll(filters=[], limit=25)
    assert len(points) == 1
    assert points[0].payload["chunk_text"] == "Last revision."


def test_transcript_chunk_settings_do_not_change_news():
    settings = Settings(_env_file=None, EMBEDDING_PROVIDER="hash", EMBEDDING_DIMENSION=64,
        EXTERNAL_EMBEDDING_PROVIDER="hash", EXTERNAL_EMBEDDING_DIMENSION=64,
        EXTERNAL_CHUNK_SIZE_CHARS=2600, TRANSCRIPT_CHUNK_SIZE_CHARS=600)
    client = QdrantClient(":memory:")
    try:
        transcript = QdrantEvidenceRepository.from_settings(settings=settings, client=client,
            collection_name="transcripts", store_name="transcript", embedding_scope="transcript")
        news = QdrantEvidenceRepository.from_settings(settings=settings, client=client,
            collection_name="news", store_name="external", embedding_scope="external")
        assert transcript.chunk_size_chars == 600
        assert news.chunk_size_chars == 2600
        with pytest.raises(ValueError, match="OVERLAP"):
            Settings(_env_file=None, TRANSCRIPT_CHUNK_OVERLAP_CHARS=600)
    finally:
        client.close()
