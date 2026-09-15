from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import main
from core.external_retriever import ExternalDocument, QdrantExternalRetriever
from config import Settings
from models.evidence_models import EvidenceBackend, EvidenceDocument, EvidenceRetrievalRequest, EvidenceSourceType
from repositories.qdrant_evidence_repository import QdrantEvidenceRepository


class StaticEmbeddingProvider:
    name = "static"
    dimension = 32

    def embed_texts(self, texts):
        return [[1.0, *([0.0] * 31)] for _ in texts]


class FakeQdrantClient:
    def __init__(self) -> None:
        self.points = []
        self.created = False
        self.query_filter = None
        self.scroll_filter = None

    def collection_exists(self, *, collection_name: str) -> bool:
        return True

    def create_collection(self, **kwargs) -> None:
        self.created = True

    def upsert(self, *, collection_name: str, points) -> None:
        self.points.extend(points)

    def query_points(self, **kwargs):
        self.query_filter = kwargs.get("query_filter")
        return SimpleNamespace(points=[{"payload": _payload(point), "score": 0.91} for point in self.points])

    def scroll(self, **kwargs):
        self.scroll_filter = kwargs.get("scroll_filter")
        return ([{"payload": _payload(point), "score": 0.0} for point in self.points], None)


def _payload(point):
    if isinstance(point, dict):
        return point["payload"]
    return point.payload


def _filter_match_value(query_filter, key):
    conditions = query_filter.get("must", []) if isinstance(query_filter, dict) else query_filter.must
    for condition in conditions:
        condition_key = condition.get("key") if isinstance(condition, dict) else condition.key
        if condition_key != key:
            continue
        match = condition.get("match") if isinstance(condition, dict) else condition.match
        return match.get("value") if isinstance(match, dict) else match.value
    return None


def _repo(client: FakeQdrantClient | None = None) -> QdrantEvidenceRepository:
    return QdrantEvidenceRepository(
        client=client or FakeQdrantClient(),
        collection_name="test_evidence",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
        chunk_size_chars=400,
        chunk_overlap_chars=0,
    )


def test_qdrant_repository_upserts_evidence_chunks() -> None:
    client = FakeQdrantClient()
    repo = _repo(client)

    accepted = repo.add_documents(
        [
            EvidenceDocument(
                document_id="manual:NVDA:call-1",
                ticker="NVDA",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="manual",
                title="NVIDIA Q1 earnings call transcript",
                published_at=datetime(2026, 5, 1, tzinfo=UTC),
                source_url="https://example.test/nvda",
                content="Guidance improved and data center demand accelerated.",
                reliability_score=0.88,
                metadata={"provider": "manual", "provider_id": "call-1", "fiscal_quarter": "Q1_2026"},
            )
        ]
    )

    assert accepted == 1
    payload = _payload(client.points[0])
    assert payload["store"] == "evidence"
    assert payload["document_id"] == "manual:NVDA:call-1"
    assert payload["ticker"] == "NVDA"
    assert payload["source_type"] == "EARNINGS_CALL"
    assert payload["fiscal_quarter"] == "Q1_2026"
    assert payload["chunk_text"] == "Guidance improved and data center demand accelerated."


def test_qdrant_repository_search_returns_qdrant_citations() -> None:
    repo = _repo()
    repo.add_documents(
        [
            EvidenceDocument(
                document_id="manual:NVDA:call-1",
                ticker="NVDA",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="manual",
                title="NVIDIA Q1 earnings call transcript",
                content="Margin expanded as demand accelerated.",
                reliability_score=0.88,
            )
        ]
    )

    result = repo.search(EvidenceRetrievalRequest(ticker="NVDA", query="NVDA margin demand", top_k=3))

    assert result.backend == EvidenceBackend.QDRANT
    assert result.evidence
    assert result.evidence[0].document_id == "manual:NVDA:call-1"
    assert result.evidence[0].confidence_score > 0.85


def test_qdrant_repository_finds_latest_transcript() -> None:
    repo = _repo()
    repo.add_documents(
        [
            EvidenceDocument(
                document_id="manual:NVDA:old",
                ticker="NVDA",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="manual",
                title="Old call",
                published_at=datetime(2025, 8, 1, tzinfo=UTC),
                content="Old transcript.",
                metadata={"fiscal_quarter": "Q2_2025"},
            ),
            EvidenceDocument(
                document_id="manual:NVDA:new",
                ticker="NVDA",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="manual",
                title="New call",
                published_at=datetime(2026, 2, 1, tzinfo=UTC),
                content="New transcript.",
                metadata={"fiscal_quarter": "Q4_2025"},
            ),
        ]
    )

    latest = repo.find_latest_transcript(ticker="NVDA", before=datetime(2026, 6, 1, tzinfo=UTC))

    assert latest is not None
    assert latest["document_id"] == "manual:NVDA:new"
    assert latest["fiscal_quarter"] == "Q4_2025"
    assert _filter_match_value(repo.client.scroll_filter, "embedding_version") == "static-32-v1"


def test_qdrant_repository_requires_location_without_injected_client() -> None:
    with pytest.raises(RuntimeError, match="QDRANT_URL or QDRANT_PATH"):
        QdrantEvidenceRepository(
            collection_name="test_evidence",
            embedding_provider=StaticEmbeddingProvider(),
            embedding_dimension=4,
        )


def test_qdrant_repository_from_settings_allows_collection_override(tmp_path) -> None:
    settings = Settings(
        VECTOR_STORE_BACKEND="qdrant",
        QDRANT_PATH=str(tmp_path),
        QDRANT_URL="",
        QDRANT_COLLECTION_NAME="main_evidence",
        QDRANT_TRANSCRIPT_COLLECTION_NAME="transcript_evidence",
        EMBEDDING_PROVIDER="hash",
        EMBEDDING_DIMENSION=64,
    )

    repo = QdrantEvidenceRepository.from_settings(
        settings=settings,
        collection_name=settings.qdrant_transcript_collection_name,
        store_name="transcript",
    )

    assert repo.collection_name == "transcript_evidence"
    assert repo.store_name == "transcript"


def test_main_builders_select_external_and_transcript_embedding_scopes(monkeypatch) -> None:
    monkeypatch.setattr(
        QdrantEvidenceRepository,
        "_build_client",
        staticmethod(lambda **kwargs: FakeQdrantClient()),
    )
    monkeypatch.setattr(QdrantEvidenceRepository, "_ensure_collection", lambda self: None)
    settings = Settings(
        VECTOR_STORE_BACKEND="qdrant",
        QDRANT_PATH="",
        QDRANT_URL="http://qdrant.test",
        QDRANT_COLLECTION_NAME="main_evidence",
        QDRANT_TRANSCRIPT_COLLECTION_NAME="transcript_evidence",
        EMBEDDING_PROVIDER="gemini",
        EMBEDDING_MODEL="gemini-embedding-001",
        EMBEDDING_DIMENSION=768,
        EMBEDDING_VERSION="gemini-embedding-001-768-v1",
        EXTERNAL_EMBEDDING_PROVIDER="openai",
        EXTERNAL_EMBEDDING_MODEL="text-embedding-3-small",
        EXTERNAL_EMBEDDING_DIMENSION=512,
        EXTERNAL_EMBEDDING_VERSION="openai-text-embedding-3-small-512-v1",
    )

    evidence_repo = main._build_evidence_repository(settings, None)
    transcript_repo = main._build_transcript_repository(settings)

    assert evidence_repo.store_name == "external"
    assert evidence_repo.embedding_provider.name == "openai"
    assert evidence_repo.embedding_dimension == 512
    assert evidence_repo.embedding_version == "openai-text-embedding-3-small-512-v1"
    assert transcript_repo.store_name == "transcript"
    assert transcript_repo.embedding_provider.name == "gemini"
    assert transcript_repo.embedding_dimension == 768
    assert transcript_repo.embedding_version == "gemini-embedding-001-768-v1"


def test_qdrant_repository_rejects_unknown_embedding_provider(tmp_path) -> None:
    settings = Settings(
        VECTOR_STORE_BACKEND="qdrant",
        QDRANT_PATH=str(tmp_path),
        QDRANT_URL="",
        EMBEDDING_PROVIDER="typo-provider",
        EMBEDDING_DIMENSION=64,
    )

    with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
        QdrantEvidenceRepository.from_settings(settings=settings)


def test_qdrant_repository_uses_store_name_in_payload() -> None:
    client = FakeQdrantClient()
    repo = QdrantEvidenceRepository(
        client=client,
        collection_name="transcript_evidence",
        store_name="transcript",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
        chunk_size_chars=400,
        chunk_overlap_chars=0,
    )

    repo.add_documents(
        [
            EvidenceDocument(
                document_id="manual:NVDA:call-1",
                ticker="NVDA",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="manual",
                title="NVIDIA Q1 earnings call transcript",
                content="Speaker turn text for transcript storage.",
                metadata={"fiscal_quarter": "Q1_2027"},
            )
        ]
    )

    payload = _payload(client.points[0])
    assert payload["store"] == "transcript"
    assert payload["embedding_provider"] == "static"
    assert payload["embedding_version"] == "static-32-v1"


def test_qdrant_repository_maps_external_payload_and_filters_embedding_version() -> None:
    client = FakeQdrantClient()
    client.points.append(
        {
            "payload": {
                "store": "external",
                "doc_id": "news:WMT:guidance",
                "ticker": "WMT",
                "text": "Walmart raised full-year sales guidance to four to five percent.",
                "title": "Walmart guidance update",
                "published_at": 1_788_748_800,
                "source_type": "news",
                "url": "https://example.test/wmt",
                "embedding_provider": "gemini",
                "embedding_version": "gemini-test-v1",
                "metadata": {"provider": "wire", "reliability_score": 0.9},
            },
            "score": 0.91,
        }
    )
    repo = QdrantEvidenceRepository(
        client=client,
        collection_name="external_evidence",
        store_name="external",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
        embedding_version="gemini-test-v1",
    )

    result = repo.search(EvidenceRetrievalRequest(ticker="WMT", query="raised guidance", top_k=3))

    assert result.evidence
    citation = result.evidence[0]
    assert citation.document_id == "news:WMT:guidance"
    assert citation.source_type == EvidenceSourceType.NEWS
    assert citation.source == "wire"
    assert citation.snippet.startswith("Walmart raised full-year")
    assert citation.source_url == "https://example.test/wmt"
    assert citation.published_at == "2026-09-07"
    assert _filter_match_value(client.query_filter, "store") == "external"
    assert _filter_match_value(client.query_filter, "embedding_version") == "gemini-test-v1"


def test_qdrant_repository_reads_points_written_by_external_retriever(tmp_path) -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(path=str(tmp_path))
    try:
        provider = StaticEmbeddingProvider()
        writer = QdrantExternalRetriever(
            client=client,
            embedding_provider=provider,
            collection_name="shared_external",
            embedding_version="static-32-v1",
        )
        writer.upsert_documents(
            [
                ExternalDocument(
                    doc_id="news:WMT:integration",
                    ticker="WMT",
                    text="Walmart raised full-year sales guidance.",
                    title="Walmart guidance",
                    published_at=1_788_748_800,
                    source_type="news",
                    url="https://example.test/wmt-integration",
                    metadata={"provider": "wire"},
                )
            ]
        )
        repository = QdrantEvidenceRepository(
            client=client,
            collection_name="shared_external",
            store_name="external",
            embedding_provider=provider,
            embedding_dimension=32,
            embedding_version="static-32-v1",
        )

        result = repository.search(
            EvidenceRetrievalRequest(ticker="WMT", query="raised sales guidance", top_k=3)
        )

        assert result.missing_evidence is False
        assert result.evidence[0].document_id == "news:WMT:integration"
        assert result.evidence[0].snippet == "Walmart raised full-year sales guidance."
        assert result.evidence[0].source_type == EvidenceSourceType.NEWS
    finally:
        client.close()


def test_qdrant_repository_merges_request_scoped_documents_without_upsert() -> None:
    client = FakeQdrantClient()
    repo = QdrantEvidenceRepository(
        client=client,
        collection_name="external_evidence",
        store_name="external",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
    )

    result = repo.search(
        EvidenceRetrievalRequest(
            ticker="WMT",
            query="raised sales guidance",
            documents=[
                EvidenceDocument(
                    document_id="request:WMT:guidance",
                    ticker="WMT",
                    source_type=EvidenceSourceType.EARNINGS_RELEASE,
                    source="request payload",
                    content="Walmart raised full-year sales guidance.",
                    reliability_score=0.9,
                )
            ],
        )
    )

    assert result.evidence
    assert result.evidence[0].document_id == "request:WMT:guidance"
    assert client.points == []


def test_qdrant_repository_rejects_existing_collection_dimension_mismatch() -> None:
    class DimensionMismatchClient(FakeQdrantClient):
        def get_collection(self, *, collection_name):
            return SimpleNamespace(
                config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=768)))
            )

    with pytest.raises(RuntimeError, match="collection=768, configured=512"):
        QdrantEvidenceRepository(
            client=DimensionMismatchClient(),
            collection_name="existing_evidence",
            embedding_provider=StaticEmbeddingProvider(),
            embedding_dimension=512,
        )


def test_transcript_repository_chunks_by_speaker_turn_and_stores_current_speaker_only() -> None:
    client = FakeQdrantClient()
    repo = QdrantEvidenceRepository(
        client=client,
        collection_name="transcript_evidence",
        store_name="transcript",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
        chunk_size_chars=400,
        chunk_overlap_chars=0,
    )

    accepted = repo.add_documents(
        [
            EvidenceDocument(
                document_id="manual:NVDA:call-1",
                ticker="NVDA",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="manual",
                title="NVIDIA Q1 earnings call transcript",
                content=(
                    "Operator: Welcome to the call. "
                    "Colette Kress: Data center revenue accelerated and margins expanded."
                ),
                metadata={
                    "fiscal_quarter": "Q1_2027",
                    "speaker_turn_count": 2,
                    "speaker_turns": [
                        {"speaker": "Operator", "text": "Welcome to the call and thank you for joining."},
                        {
                            "speaker": "Colette Kress",
                            "text": "Data center revenue accelerated and margins expanded.",
                        },
                    ],
                },
            )
        ]
    )

    assert accepted == 1
    assert len(client.points) == 2
    first_payload = _payload(client.points[0])
    second_payload = _payload(client.points[1])
    assert first_payload["speaker"] == "Operator"
    assert first_payload["turn_index"] == 0
    assert first_payload["chunk_text"] == "Welcome to the call and thank you for joining."
    assert first_payload["speaker_turn_count"] == 2
    assert "metadata_json" not in first_payload
    assert second_payload["speaker"] == "Colette Kress"
    assert second_payload["turn_index"] == 1
    assert second_payload["chunk_text"] == "Data center revenue accelerated and margins expanded."
