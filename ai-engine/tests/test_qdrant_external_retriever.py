from __future__ import annotations

from pathlib import Path

from config import Settings
from core.external_retriever import ExternalDocument, QdrantExternalRetriever


def test_qdrant_retriever_uses_real_local_backend(monkeypatch, tmp_path: Path) -> None:
    from config import get_settings

    monkeypatch.setenv("VECTOR_STORE_BACKEND", "qdrant")
    monkeypatch.setenv("QDRANT_URL", "")
    monkeypatch.setenv("QDRANT_PATH", str(tmp_path / "qdrant"))
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "evidence_test")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    get_settings.cache_clear()
    retriever = QdrantExternalRetriever()
    retriever.upsert_documents(
        [
            ExternalDocument(
                doc_id="filing-1",
                ticker="NVDA",
                title="Guidance update",
                text="NVIDIA raised guidance as data center demand and margins improved.",
                published_at=1000,
                source_type="filing",
                importance=0.95,
            )
        ]
    )
    result = retriever.retrieve(
        query="data center guidance margin",
        ticker="NVDA",
        chunk_timestamp=1100,
        preferred_sources=["filing"],
        lookback_days=30,
    )

    assert result and result[0].doc_id == "filing-1"
    assert retriever.get_stats()["effective_backend"] == "qdrant"
    retriever.close()
    get_settings.cache_clear()
