from datetime import UTC, datetime

from qdrant_client import QdrantClient

from core.external_retriever import ExternalDocument, HashEmbeddingProvider, QdrantExternalRetriever
from models.evidence_models import EvidenceDocument, EvidenceRetrievalRequest
from repositories.evidence_store_repository import EvidenceStoreRepository
from repositories.qdrant_evidence_repository import QdrantEvidenceRepository


def test_local_search_excludes_other_ticker_and_future_before_top_k():
    repository = EvidenceStoreRepository(documents=[
        EvidenceDocument(document_id="future", ticker="WMT", content="strong revenue guidance growth",
            published_at=datetime(2026, 9, 17, tzinfo=UTC)),
        EvidenceDocument(document_id="other", ticker="NVDA", content="strong revenue guidance growth",
            published_at=datetime(2026, 9, 14, tzinfo=UTC)),
        EvidenceDocument(document_id="unknown", ticker="WMT", content="strong revenue guidance growth"),
        EvidenceDocument(document_id="prior", ticker="WMT", content="revenue guidance",
            published_at=datetime(2026, 9, 14, tzinfo=UTC)),
    ])
    result = repository.search(EvidenceRetrievalRequest(ticker="WMT", query="strong revenue guidance growth",
        top_k=1, metadata={"as_of": "2026-09-15T00:00:00Z"}))
    assert [item.document_id for item in result.evidence] == ["prior"]


def test_qdrant_excludes_future_before_top_k():
    client = QdrantClient(":memory:")
    provider = HashEmbeddingProvider(dimension=64)
    try:
        writer = QdrantExternalRetriever(client=client, embedding_provider=provider,
            collection_name="test", embedding_version="hash-test")
        writer.upsert_documents([
            ExternalDocument(doc_id="future", ticker="WMT", text="strong revenue guidance growth",
                published_at=int(datetime(2026, 9, 17, tzinfo=UTC).timestamp())),
            ExternalDocument(doc_id="prior", ticker="WMT", text="revenue guidance",
                published_at=int(datetime(2026, 9, 14, tzinfo=UTC).timestamp())),
        ])
        reader = QdrantEvidenceRepository(client=client, embedding_provider=provider, embedding_dimension=64,
            collection_name="test", store_name="external", embedding_version="hash-test")
        result = reader.search(EvidenceRetrievalRequest(ticker="WMT", query="strong revenue guidance growth",
            top_k=1, metadata={"as_of": "2026-09-15T00:00:00Z"}))
        assert [item.document_id for item in result.evidence] == ["prior"]
    finally:
        client.close()
