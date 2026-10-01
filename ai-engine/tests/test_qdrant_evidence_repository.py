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


def _filter_conditions(query_filter):
    if query_filter is None:
        return []
    return query_filter.get("must", []) if isinstance(query_filter, dict) else list(query_filter.must)


def _condition_parts(condition):
    if isinstance(condition, dict):
        return condition.get("key"), condition.get("match"), condition.get("range")
    return (
        getattr(condition, "key", None),
        getattr(condition, "match", None),
        getattr(condition, "range", None),
    )


def _payload_matches(payload, query_filter) -> bool:
    """Qdrant 의 must 조건을 payload 에 실제로 적용한다.

    필터를 기록만 하고 전부 돌려주면, 조회에서 포인트를 걸러 내는 필터를 더하거나 빼도
    테스트가 통과한다. 그 차이가 이 저장소에서 실제로 문제가 되는 지점이라
    (embedding_version 필터 하나로 68청크가 0건이 되었다) 여기서 걸러 준다.
    """
    for condition in _filter_conditions(query_filter):
        key, match, rng = _condition_parts(condition)
        if key is None:
            continue
        actual = payload.get(key)
        if match is not None:
            if isinstance(match, dict):
                expected, any_values = match.get("value"), match.get("any")
            else:
                expected = getattr(match, "value", None)
                any_values = getattr(match, "any", None)
            if any_values is not None:
                if actual not in list(any_values):
                    return False
            elif actual != expected:
                return False
        if rng is not None:
            lt = rng.get("lt") if isinstance(rng, dict) else getattr(rng, "lt", None)
            if lt is not None and not (actual is not None and actual < lt):
                return False
    return True


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

    def _matching(self, query_filter):
        return [point for point in self.points if _payload_matches(_payload(point), query_filter)]

    def query_points(self, **kwargs):
        self.query_filter = kwargs.get("query_filter")
        matched = self._matching(self.query_filter)
        limit = kwargs.get("limit")
        if limit is not None:
            matched = matched[: int(limit)]
        return SimpleNamespace(points=[{"payload": _payload(point), "score": 0.91} for point in matched])

    def scroll(self, **kwargs):
        self.scroll_filter = kwargs.get("scroll_filter")
        matched = self._matching(self.scroll_filter)
        return ([{"payload": _payload(point), "score": 0.0} for point in matched], None)


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
    # 임베딩 호환성은 컬렉션 단위로 보장한다 — 조회에 embedding_version 을 걸지 않는다
    assert _filter_match_value(repo.client.scroll_filter, "embedding_version") is None


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


def test_qdrant_repository_maps_external_payload() -> None:
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
    assert _filter_match_value(client.query_filter, "ticker") == "WMT"


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


def _stored_point(**overrides):
    """저장소가 쓴 형태의 포인트. embedding_version 을 바꿔 가며 쓰려고 둔다."""
    payload = {
        "store": "evidence",
        "document_id": "manual:WMT:prior",
        "doc_id": "manual:WMT:prior",
        "ticker": "WMT",
        "text": "Walmart reported 7,200 rollbacks in the prior quarter.",
        "content": "Walmart reported 7,200 rollbacks in the prior quarter.",
        "title": "Prior call",
        "source_type": EvidenceSourceType.EARNINGS_CALL.value,
        "published_at_epoch": 1_780_000_000,
        "embedding_provider": "gemini",
        "embedding_version": "gemini-embedding-001-768-v1",
    }
    payload.update(overrides)
    return {"payload": payload, "score": 0.91}


def test_search_returns_points_whose_embedding_version_differs() -> None:
    """저장된 값과 설정이 달라도 조회된다.

    임베딩 호환성은 컬렉션 단위로 보장하므로 조회 단계에서 걸러내지 않는다. 필터를 걸면
    설정을 바꾸거나 값이 없는 기존 포인트가 통째로 빠지는데, 서버에서 트랜스크립트 68청크가
    0건이 된 것이 이 경우였다.
    """
    client = FakeQdrantClient()
    client.points.append(_stored_point())
    client.points.append(_stored_point(document_id="manual:WMT:legacy", doc_id="manual:WMT:legacy"))
    client.points[1]["payload"].pop("embedding_version")  # 버전 없이 적재된 옛 포인트
    repo = QdrantEvidenceRepository(
        client=client,
        collection_name="test_evidence",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
        embedding_version="hash-32-v2",  # 저장된 값과 다른 설정
    )

    result = repo.search(EvidenceRetrievalRequest(ticker="WMT", query="rollbacks", top_k=5))

    assert len(result.evidence) == 2
    assert _filter_match_value(client.query_filter, "embedding_version") is None


def test_search_still_filters_store_and_ticker() -> None:
    """버전 필터를 뺀 것이 다른 필터까지 느슨해진 것은 아니다."""
    client = FakeQdrantClient()
    client.points.append(_stored_point())
    client.points.append(_stored_point(ticker="NVDA", document_id="manual:NVDA:x", doc_id="manual:NVDA:x"))
    client.points.append(_stored_point(store="external", document_id="news:WMT:y", doc_id="news:WMT:y"))
    repo = _repo(client)

    result = repo.search(EvidenceRetrievalRequest(ticker="WMT", query="rollbacks", top_k=5))

    assert [item.document_id for item in result.evidence] == ["manual:WMT:prior"]


def test_prior_transcript_chunks_ignore_embedding_version() -> None:
    client = FakeQdrantClient()
    client.points.append(_stored_point())
    repo = QdrantEvidenceRepository(
        client=client,
        collection_name="test_evidence",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
        embedding_version="hash-32-v2",
    )

    citations = repo.search_prior_transcript_chunks(
        ticker="WMT", query="rollbacks", document_id="manual:WMT:prior", top_k=3
    )

    assert [item.document_id for item in citations] == ["manual:WMT:prior"]
    assert _filter_match_value(client.query_filter, "embedding_version") is None
    assert _filter_match_value(client.query_filter, "document_id") == "manual:WMT:prior"


def test_find_latest_transcript_ignores_embedding_version() -> None:
    client = FakeQdrantClient()
    client.points.append(_stored_point())
    repo = QdrantEvidenceRepository(
        client=client,
        collection_name="test_evidence",
        embedding_provider=StaticEmbeddingProvider(),
        embedding_dimension=4,
        embedding_version="hash-32-v2",
    )

    latest = repo.find_latest_transcript(ticker="WMT", before=datetime(2026, 6, 1, tzinfo=UTC))

    assert latest is not None
    assert latest["document_id"] == "manual:WMT:prior"


def test_embedding_version_is_still_written_to_payload() -> None:
    """조회에는 안 쓰지만 추적용으로는 남긴다."""
    client = FakeQdrantClient()
    repo = _repo(client)
    repo.add_documents(
        [
            EvidenceDocument(
                document_id="manual:WMT:new",
                ticker="WMT",
                source_type=EvidenceSourceType.EARNINGS_CALL,
                source="manual",
                title="Call",
                published_at=datetime(2026, 2, 1, tzinfo=UTC),
                content="Transcript body.",
                metadata={},
            )
        ]
    )

    assert client.points
    assert _payload(client.points[0])["embedding_version"] == "static-32-v1"


def test_real_qdrant_reads_points_whose_embedding_version_differs(tmp_path) -> None:
    """Fake 가 아닌 실제 Qdrant 엔진으로 정책을 고정한다.

    적재 시점의 `embedding_version` 과 조회 시점의 설정이 달라도 조회된다.
    서버에서 트랜스크립트 68청크가 0건이 된 것이 이 상황이었고, Fake 의 필터 구현에
    기대지 않고 확인해 두려고 둔다.
    """
    from qdrant_client import QdrantClient

    client = QdrantClient(path=str(tmp_path))
    try:
        provider = StaticEmbeddingProvider()
        writer = QdrantExternalRetriever(
            client=client,
            embedding_provider=provider,
            collection_name="shared_external",
            embedding_version="gemini-embedding-001-768-v1",  # 적재 당시 버전
        )
        writer.upsert_documents(
            [
                ExternalDocument(
                    doc_id="news:WMT:legacy-version",
                    ticker="WMT",
                    text="Walmart reported 8,500 rollbacks this quarter.",
                    title="Walmart rollbacks",
                    published_at=1_788_748_800,
                    source_type="news",
                    url="https://example.test/wmt-legacy",
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
            embedding_version="static-32-v9",  # 적재 당시와 다른 현재 설정
        )
        result = repository.search(
            EvidenceRetrievalRequest(ticker="WMT", query="rollbacks", top_k=3)
        )

        assert result.missing_evidence is False
        assert result.evidence[0].document_id == "news:WMT:legacy-version"

        # 외부 retriever 쪽도 같은 정책이다 — 분석 경로가 실제로 쓰는 경로다
        reader = QdrantExternalRetriever(
            client=client,
            embedding_provider=provider,
            collection_name="shared_external",
            embedding_version="static-32-v9",
        )
        documents = reader.retrieve(
            query="rollbacks",
            ticker="WMT",
            chunk_timestamp=1_788_752_400,
            preferred_sources=["news"],
            lookback_days=30,
        )
        assert [item.doc_id for item in documents] == ["news:WMT:legacy-version"]
    finally:
        client.close()
