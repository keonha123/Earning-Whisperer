from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
import sys

import pytest

from config import get_settings
from core.external_retriever import (
    ExternalDocument,
    HashEmbeddingProvider,
    InMemoryExternalRetriever,
    OpenAIEmbeddingProvider,
    QdrantExternalRetriever,
    _bm25_lexical_scores,
    _build_embedding_provider,
    _business_signal_score,
    _chunk_document,
    external_retriever,
)


@dataclass
class _FakePoint:
    id: str
    vector: dict[str, list[float]]
    payload: dict[str, Any]
    score: float = 0.0


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, _FakePoint]] = {}

    def get_collection(self, collection_name: str):
        if collection_name not in self.collections:
            raise RuntimeError("missing collection")
        return {"name": collection_name}

    def create_collection(self, collection_name: str, vectors_config):
        self.collections.setdefault(collection_name, {})

    def delete_collection(self, collection_name: str):
        self.collections.pop(collection_name, None)

    def delete(self, collection_name: str, points_selector, wait: bool = True):
        del wait
        collection = self.collections.get(collection_name, {})
        query_filter = _selector_filter(points_selector)
        for point_id in [
            point.id
            for point in collection.values()
            if self._matches_filter(point.payload, query_filter)
        ]:
            collection.pop(point_id, None)

    def count(self, collection_name: str, count_filter, exact: bool = True):
        del exact
        return SimpleNamespace(
            count=len(self._filter_points(collection_name, count_filter))
        )

    def upsert(self, collection_name: str, points):
        collection = self.collections.setdefault(collection_name, {})
        for point in points:
            normalized = self._normalize_point(point)
            collection[normalized.id] = normalized

    def search(self, collection_name: str, query_vector, query_filter, limit: int, with_payload: bool):
        del with_payload
        query = self._extract_dense_vector(query_vector)
        results: list[_FakePoint] = []
        for point in self._filter_points(collection_name, query_filter):
            dense = self._extract_dense_vector(point.vector)
            score = sum(left * right for left, right in zip(query, dense))
            if score <= 0.0:
                continue
            results.append(_FakePoint(id=point.id, vector=point.vector, payload=point.payload, score=score))
        results.sort(key=lambda item: (-item.score, item.id))
        return results[:limit]

    def scroll(self, collection_name: str, scroll_filter, limit: int, with_payload: bool):
        del with_payload
        points = self._filter_points(collection_name, scroll_filter)
        points.sort(key=lambda item: item.id)
        return points[:limit], None

    def _filter_points(self, collection_name: str, query_filter) -> list[_FakePoint]:
        collection = self.collections.get(collection_name, {})
        return [
            point
            for point in collection.values()
            if self._matches_filter(point.payload, query_filter)
        ]

    def _matches_filter(self, payload: dict[str, Any], query_filter: Any) -> bool:
        for condition in _filter_conditions(query_filter):
            key = _condition_key(condition)
            if not key:
                continue
            value = payload.get(key)
            match = _condition_match(condition)
            if match is not None:
                allowed_any = _match_any(match)
                if allowed_any is not None:
                    if value not in allowed_any:
                        return False
                else:
                    exact = _match_value(match)
                    if exact is not None and value != exact:
                        return False
            range_filter = _condition_range(condition)
            if range_filter is not None:
                gte = _range_value(range_filter, "gte")
                lte = _range_value(range_filter, "lte")
                numeric = int(value or 0)
                if gte is not None and numeric < gte:
                    return False
                if lte is not None and numeric > lte:
                    return False
                lt = _range_value(range_filter, "lt")
                if lt is not None and numeric >= lt:
                    return False
        return True

    @staticmethod
    def _extract_dense_vector(vector_payload: Any) -> list[float]:
        if isinstance(vector_payload, dict):
            return list(vector_payload.get("dense", []))
        return list(vector_payload)

    @staticmethod
    def _normalize_point(point: Any) -> _FakePoint:
        if isinstance(point, dict):
            return _FakePoint(
                id=str(point["id"]),
                vector=dict(point["vector"]),
                payload=dict(point["payload"]),
            )
        return _FakePoint(
            id=str(getattr(point, "id")),
            vector=dict(getattr(point, "vector")),
            payload=dict(getattr(point, "payload")),
        )


def _filter_conditions(query_filter: Any) -> list[Any]:
    if isinstance(query_filter, dict):
        return list(query_filter.get("must", []))
    return list(getattr(query_filter, "must", []) or [])


def _selector_filter(points_selector: Any) -> Any:
    if isinstance(points_selector, dict):
        return points_selector.get("filter", {})
    return getattr(points_selector, "filter", {})


def _condition_key(condition: Any) -> str:
    if isinstance(condition, dict):
        return str(condition.get("key", ""))
    return str(getattr(condition, "key", ""))


def _condition_match(condition: Any) -> Any:
    if isinstance(condition, dict):
        return condition.get("match")
    return getattr(condition, "match", None)


def _condition_range(condition: Any) -> Any:
    if isinstance(condition, dict):
        return condition.get("range")
    return getattr(condition, "range", None)


def _match_any(match: Any) -> list[str] | None:
    if isinstance(match, dict):
        values = match.get("any")
        return list(values) if values is not None else None
    values = getattr(match, "any", None)
    return list(values) if values is not None else None


def _match_value(match: Any) -> Any:
    if isinstance(match, dict):
        return match.get("value")
    return getattr(match, "value", None)


def _range_value(range_filter: Any, key: str) -> int | None:
    if isinstance(range_filter, dict):
        value = range_filter.get(key)
    else:
        value = getattr(range_filter, key, None)
    return None if value is None else int(value)


@pytest.fixture(autouse=True)
def clear_retriever_state():
    get_settings.cache_clear()
    external_retriever.reset_backend()
    yield
    external_retriever.reset_backend()
    get_settings.cache_clear()


def test_external_retriever_uses_qdrant_backend_when_configured(monkeypatch):
    fake_client = _FakeQdrantClient()
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "qdrant")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    monkeypatch.setattr(QdrantExternalRetriever, "_build_client", staticmethod(lambda: fake_client))

    external_retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="filing-1",
                ticker="NVDA",
                title="8-K guidance update",
                text="The company raised full-year guidance and margin outlook.",
                published_at=10,
                source_type="filing",
                importance=0.95,
            )
        ]
    )

    results = external_retriever.retrieve(
        query="NVDA guidance update margin outlook",
        ticker="NVDA",
        chunk_timestamp=11,
        preferred_sources=["filing"],
        lookback_days=7,
    )
    stats = external_retriever.get_stats()

    assert [item.doc_id for item in results] == ["filing-1"]
    assert stats["effective_backend"] == "qdrant"
    assert stats["requested_backend"] == "qdrant"


def test_qdrant_retriever_applies_filters_and_merges_keyword_candidates():
    fake_client = _FakeQdrantClient()
    retriever = QdrantExternalRetriever(
        client=fake_client,
        embedder=HashEmbeddingProvider(dimension=128),
        requested_backend="qdrant",
    )

    retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="filing-1",
                ticker="NVDA",
                title="8-K guidance update",
                text="The company raised full-year guidance and margin outlook.",
                published_at=1741826900,
                source_type="filing",
                form_type="8-K",
                importance=0.95,
            ),
            ExternalDocument(
                doc_id="news-1",
                ticker="NVDA",
                title="Analysts note stronger outlook",
                text="Analysts highlighted the guidance change after the filing update.",
                published_at=1741826800,
                source_type="news",
                importance=0.60,
            ),
            ExternalDocument(
                doc_id="future-news",
                ticker="NVDA",
                title="Published too late",
                text="This article should be filtered because it was published after the chunk.",
                published_at=1741827100,
                source_type="news",
                importance=0.70,
            ),
        ]
    )

    results = retriever.retrieve(
        query="NVDA guidance update filing outlook",
        ticker="NVDA",
        chunk_timestamp=1741827000,
        preferred_sources=["filing", "news"],
        lookback_days=7,
        limit=3,
    )

    assert {item.doc_id for item in results} == {"filing-1", "news-1"}
    assert results[0].score >= results[1].score
    assert all(item.doc_id != "future-news" for item in results)
    assert retriever.get_stats()["effective_backend"] == "qdrant"


def test_qdrant_retriever_deletes_documents_older_than_retention_window(monkeypatch):
    monkeypatch.setenv("EXTERNAL_EVIDENCE_RETENTION_DAYS", "30")
    get_settings.cache_clear()
    fake_client = _FakeQdrantClient()
    retriever = QdrantExternalRetriever(
        client=fake_client,
        embedder=HashEmbeddingProvider(dimension=128),
        requested_backend="qdrant",
    )
    now = 1_800_000_000
    day = 86_400

    retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="expired-news",
                ticker="NVDA",
                title="Expired news",
                text="Old guidance article.",
                published_at=now - 31 * day,
                source_type="news",
            ),
            ExternalDocument(
                doc_id="fresh-news",
                ticker="NVDA",
                title="Fresh news",
                text="Recent guidance article.",
                published_at=now - 29 * day,
                source_type="news",
            ),
            ExternalDocument(
                doc_id="unknown-date",
                ticker="NVDA",
                title="Unknown date",
                text="Document without a published timestamp.",
                published_at=0,
                source_type="news",
            ),
        ]
    )

    result = retriever.delete_expired_documents(now=now)

    assert result["status"] == "completed"
    assert result["cutoff_timestamp"] == now - 30 * day
    assert result["deleted_count"] == 1
    remaining_doc_ids = {
        point.payload["doc_id"]
        for point in fake_client.collections[retriever._collection_name].values()
    }
    assert remaining_doc_ids == {"fresh-news", "unknown-date"}


def test_memory_retriever_deletes_documents_older_than_retention_window(monkeypatch):
    monkeypatch.setenv("EXTERNAL_EVIDENCE_RETENTION_DAYS", "30")
    get_settings.cache_clear()
    retriever = InMemoryExternalRetriever()
    now = 1_800_000_000
    day = 86_400
    retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="expired-news",
                ticker="NVDA",
                text="Old guidance article.",
                published_at=now - 31 * day,
            ),
            ExternalDocument(
                doc_id="fresh-news",
                ticker="NVDA",
                text="Recent guidance article.",
                published_at=now - 29 * day,
            ),
            ExternalDocument(
                doc_id="unknown-date",
                ticker="NVDA",
                text="Document without a published timestamp.",
                published_at=0,
            ),
        ]
    )

    result = retriever.delete_expired_documents(now=now)

    assert result["deleted_count"] == 1
    assert set(retriever._documents) == {"fresh-news", "unknown-date"}


def test_bm25_lexical_scores_prioritize_exact_event_terms():
    documents = [
        ExternalDocument(
            doc_id="filing-1",
            ticker="NVDA",
            title="8-K guidance update",
            text="The company raised full-year guidance and margin outlook.",
            published_at=10,
            source_type="filing",
        ),
        ExternalDocument(
            doc_id="news-1",
            ticker="NVDA",
            title="Analysts remain constructive",
            text="Analysts discussed resilient demand and strong execution.",
            published_at=10,
            source_type="news",
        ),
    ]

    scores = _bm25_lexical_scores(
        query="NVDA guidance update margin outlook",
        query_tokens={"nvda", "guidance", "update", "margin", "outlook"},
        documents=documents,
    )

    assert scores["filing-1"] > scores.get("news-1", 0.0)
    assert scores["filing-1"] > 0.0


def test_business_signal_depends_only_on_recency():
    recent_score = _business_signal_score(
        document=ExternalDocument(
            doc_id="filing-1",
            ticker="NVDA",
            text="Raised guidance.",
            published_at=1741826900,
            source_type="filing",
            importance=0.95,
        ),
        chunk_timestamp=1741827000,
        lookback_days=7,
    )
    older_score = _business_signal_score(
        document=ExternalDocument(
            doc_id="news-1",
            ticker="NVDA",
            text="Generic commentary.",
            published_at=1741200000,
            source_type="news",
            importance=0.40,
        ),
        chunk_timestamp=1741827000,
        lookback_days=7,
    )

    assert recent_score > older_score


def test_chunk_document_uses_token_windows_and_overlap(monkeypatch):
    monkeypatch.setenv("EXTERNAL_CHUNK_SIZE_TOKENS", "5")
    monkeypatch.setenv("EXTERNAL_CHUNK_OVERLAP_TOKENS", "2")
    monkeypatch.setattr(
        "core.external_retriever._encode_chunk_tokens",
        lambda text: list(range(12)),
    )
    monkeypatch.setattr(
        "core.external_retriever._decode_chunk_tokens",
        lambda token_ids: " ".join(f"t{i}" for i in token_ids),
    )
    get_settings.cache_clear()

    document = ExternalDocument(
        doc_id="news-1",
        ticker="NVDA",
        text="placeholder",
    )

    chunks = _chunk_document(document)

    assert [chunk.doc_id for chunk in chunks] == [
        "news-1#chunk-0",
        "news-1#chunk-1",
        "news-1#chunk-2",
        "news-1#chunk-3",
    ]
    assert [chunk.text for chunk in chunks] == [
        "t0 t1 t2 t3 t4",
        "t3 t4 t5 t6 t7",
        "t6 t7 t8 t9 t10",
        "t9 t10 t11",
    ]
    assert all(chunk.metadata["original_doc_id"] == "news-1" for chunk in chunks)


def test_openai_embedding_provider_uses_text_embedding_3_large(monkeypatch):
    captured: dict[str, Any] = {}
    embedding_a = [float(index) for index in range(64)]
    embedding_b = [float(index) for index in range(64, 128)]

    class _FakeEmbeddings:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(embedding=embedding_a),
                    SimpleNamespace(embedding=embedding_b),
                ]
            )

    class _FakeOpenAIClient:
        def __init__(self, *, api_key: str):
            captured["api_key"] = api_key
            self.embeddings = _FakeEmbeddings()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "64")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=_FakeOpenAIClient))
    get_settings.cache_clear()

    provider = _build_embedding_provider()
    assert isinstance(provider, OpenAIEmbeddingProvider)

    embeddings = provider.embed_texts(["alpha", "beta"])

    assert embeddings == [embedding_a, embedding_b]
    assert captured["api_key"] == "test-openai-key"
    assert captured["model"] == "text-embedding-3-large"
    assert captured["input"] == ["alpha", "beta"]
    assert captured["dimensions"] == 64
    assert captured["encoding_format"] == "float"
