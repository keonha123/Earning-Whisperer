from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from config import Settings
from models.evidence_models import EvidenceBackend, EvidenceDocument, EvidenceRetrievalRequest, EvidenceSourceType
from repositories.qdrant_evidence_repository import QdrantEvidenceRepository


class StaticEmbeddingProvider:
    name = "static"
    dimension = 4

    def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class FakeQdrantClient:
    def __init__(self) -> None:
        self.points = []
        self.created = False

    def collection_exists(self, *, collection_name: str) -> bool:
        return True

    def create_collection(self, **kwargs) -> None:
        self.created = True

    def upsert(self, *, collection_name: str, points) -> None:
        self.points.extend(points)

    def query_points(self, **kwargs):
        return SimpleNamespace(points=[{"payload": _payload(point), "score": 0.91} for point in self.points])

    def scroll(self, **kwargs):
        return ([{"payload": _payload(point), "score": 0.0} for point in self.points], None)


def _payload(point):
    if isinstance(point, dict):
        return point["payload"]
    return point.payload


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
