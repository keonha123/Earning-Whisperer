from __future__ import annotations

import time

from core.external_retriever import ExternalDocument, InMemoryExternalRetriever, _bm25_lexical_scores, external_retriever


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
                importance=0.95,
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
