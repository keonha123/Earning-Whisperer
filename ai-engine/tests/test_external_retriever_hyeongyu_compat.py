from __future__ import annotations

import time
from types import SimpleNamespace

from core.external_retriever import ExternalDocument, InMemoryExternalRetriever, QdrantExternalRetriever, _bm25_lexical_scores, external_retriever


class StaticEmbeddingProvider:
    name = "openai"
    dimension = 4

    def __init__(self) -> None:
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class FakeQdrantClient:
    def __init__(self) -> None:
        self.points = []
        self.query_filter = None

    def collection_exists(self, *, collection_name):
        return True

    def upsert(self, *, collection_name, points):
        self.points.extend(points)

    def query_points(self, **kwargs):
        self.query_filter = kwargs["query_filter"]
        payloads = [point.payload if hasattr(point, "payload") else point["payload"] for point in self.points]
        return SimpleNamespace(points=[{"payload": payload, "score": 0.91} for payload in payloads])


def test_memory_external_retriever_returns_prompt_ready_documents() -> None:
    retriever = InMemoryExternalRetriever()
    now = int(time.time())
    retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="nvda-filing-1",
                ticker="NVDA",
                title="8-K guidance update",
                text="NVIDIA raised full-year guidance after stronger data center demand and margin expansion.",
                published_at=now - 60,
                source_type="filing",
                form_type="8-K",
            )
        ]
    )

    results = retriever.retrieve(
        query="NVDA guidance data center margin",
        ticker="NVDA",
        chunk_timestamp=now,
        preferred_sources=["filing"],
        lookback_days=7,
    )

    assert [item.doc_id for item in results] == ["nvda-filing-1"]
    assert results[0].score > 0
    assert results[0].form_type == "8-K"
    assert retriever.get_stats()["effective_backend"] == "memory"


def test_external_retriever_facade_reset_and_stats() -> None:
    external_retriever.reset_backend()
    external_retriever.clear()
    now = int(time.time())
    external_retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="news-1",
                ticker="MSFT",
                text="Azure AI demand accelerated and management raised cloud revenue outlook.",
                published_at=now - 10,
                source_type="news",
            )
        ]
    )

    results = external_retriever.retrieve(
        query="MSFT Azure AI cloud outlook",
        ticker="MSFT",
        chunk_timestamp=now,
    )

    assert results
    assert external_retriever.get_stats()["retrieval_count"] >= 1
    external_retriever.reset_backend()


def test_bm25_scores_prioritize_exact_event_terms() -> None:
    docs = [
        ExternalDocument(doc_id="a", ticker="NVDA", title="Guidance", text="Raised guidance and margin outlook."),
        ExternalDocument(doc_id="b", ticker="NVDA", title="Generic", text="Management discussed operations."),
    ]
    scores = _bm25_lexical_scores(
        query="guidance margin outlook",
        query_tokens={"guidance", "margin", "outlook"},
        documents=docs,
    )

    assert scores["a"] > scores.get("b", 0.0)


def test_qdrant_external_retriever_versions_news_vectors_and_queries() -> None:
    now = int(time.time())
    client = FakeQdrantClient()
    retriever = QdrantExternalRetriever(
        client=client,
        embedding_provider=StaticEmbeddingProvider(),
        collection_name="test_external",
        embedding_version="openai-test-v1",
    )
    retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="news-versioned",
                ticker="NVDA",
                text="NVIDIA raised guidance after strong data center demand.",
                published_at=now - 60,
                source_type="news",
            )
        ]
    )

    payload = client.points[0].payload
    assert payload["embedding_provider"] == "openai"
    assert payload["embedding_version"] == "openai-test-v1"
    assert "importance" not in payload

    results = retriever.retrieve(
        query="NVIDIA raised guidance",
        ticker="NVDA",
        chunk_timestamp=now,
        preferred_sources=["news"],
        lookback_days=30,
    )

    assert results
    assert results[0].semantic_score == 0.91
    assert "embedding_version" in str(client.query_filter)
    assert "openai-test-v1" in str(client.query_filter)


def test_memory_retriever_excludes_future_and_expired_news() -> None:
    now = int(time.time())
    retriever = InMemoryExternalRetriever()
    retriever.upsert_documents(
        [
            ExternalDocument(doc_id="current", ticker="NVDA", text="NVIDIA raised guidance.", published_at=now - 60, source_type="news"),
            ExternalDocument(doc_id="future", ticker="NVDA", text="NVIDIA raised guidance.", published_at=now + 60, source_type="news"),
            ExternalDocument(doc_id="expired", ticker="NVDA", text="NVIDIA raised guidance.", published_at=now - 31 * 86400, source_type="news"),
        ]
    )

    results = retriever.retrieve(
        query="NVIDIA raised guidance",
        ticker="NVDA",
        chunk_timestamp=now,
        preferred_sources=["news"],
        lookback_days=30,
    )

    assert [item.doc_id for item in results] == ["current"]


def test_qdrant_retrieve_many_embeds_claims_in_one_batch() -> None:
    now = int(time.time())
    client = FakeQdrantClient()
    provider = StaticEmbeddingProvider()
    retriever = QdrantExternalRetriever(
        client=client,
        embedding_provider=provider,
        collection_name="test_external",
        embedding_version="openai-test-v1",
    )
    retriever.upsert_documents(
        [ExternalDocument(doc_id="news", ticker="NVDA", text="Revenue and margin increased.", published_at=now - 60, source_type="news")]
    )
    provider.calls.clear()

    batches = retriever.retrieve_many(
        queries=["Revenue increased.", "Margin increased."],
        ticker="NVDA",
        chunk_timestamps=[now, now - 1],
        preferred_sources=["news"],
        lookback_days=30,
        semantic_only=True,
    )

    assert provider.calls == [["Revenue increased.", "Margin increased."]]
    assert len(batches) == 2
    assert all(batch for batch in batches)
