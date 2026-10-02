from __future__ import annotations

import math
from contextlib import closing

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models

import main
from config import Settings
from core.external_retriever import ExternalDocument, InMemoryExternalRetriever, QdrantExternalRetriever
from models.request_models import MarketData, SourceType
from repositories.qdrant_evidence_repository import QdrantEvidenceRepository
from services.evidence_retrieval_service import EvidenceRetrievalService


class FixedEmbedding:
    name = "offline"
    dimension = 32

    def embed_texts(self, texts):
        return [([1.0, 0.0] + [0.0] * 30) if text.startswith("document")
                else ([0.725, math.sqrt(1 - 0.725**2)] + [0.0] * 30) for text in texts]


def test_external_confidence_matches_repository_cosine_without_requery():
    with closing(QdrantClient(":memory:")) as client:
        provider = FixedEmbedding()
        writer = QdrantExternalRetriever(client=client, embedding_provider=provider,
                                        collection_name="test", embedding_version="v1")
        writer.upsert_documents([ExternalDocument(doc_id="one", ticker="WMT",
                                text="document guidance raised", published_at=1800000000)])
        reader = QdrantEvidenceRepository(client=client, embedding_provider=provider,
                                         embedding_dimension=32, collection_name="test",
                                         store_name="external", embedding_version="v1")
        hits = writer.retrieve(query="guidance raised", ticker="WMT", chunk_timestamp=1800000000)
        service = EvidenceRetrievalService(repository=reader)
        common = dict(ticker="WMT", current_chunk="guidance raised", source_type=SourceType.EARNINGS_CALL,
                      market_data=MarketData(current_price=100), canonical_bundle=None,
                      source_health=None, request_metadata={}, evidence_documents=[])
        direct = service.retrieve_for_analysis(**common)
        reused = service.retrieve_for_analysis(**common, external_documents=hits)
        assert reused.evidence[0].relevance_score == direct.evidence[0].relevance_score == 0.725
        assert reused.coverage_score == direct.coverage_score
        assert reused.confidence_adjustment == direct.confidence_adjustment == 0.0
        assert reused.evidence[0].metadata["ranking_score"] < 0.5


def test_sparse_results_keep_weighted_relevance():
    retriever = InMemoryExternalRetriever()
    retriever.upsert_documents([ExternalDocument(doc_id="one", ticker="WMT", text="guidance raised")])
    hit = retriever.retrieve(query="guidance raised", ticker="WMT", chunk_timestamp=0)[0]
    assert hit.semantic_score_kind == "lexical"
    assert hit.semantic_score > hit.score
    citation = EvidenceRetrievalService._external_citation(hit, ticker="WMT")
    assert citation.relevance_score == hit.score


def test_qdrant_count_filters_store_and_time_and_keeps_legacy_versions():
    with closing(QdrantClient(":memory:")) as client:
        retriever = QdrantExternalRetriever(client=client, embedding_provider=FixedEmbedding(),
                                           collection_name="test", embedding_version="v1")
        retriever.upsert_documents([
            ExternalDocument(doc_id="in", ticker="WMT", text="document guidance", published_at=100),
            ExternalDocument(doc_id="future", ticker="WMT", text="document guidance", published_at=201),
            ExternalDocument(doc_id="past", ticker="WMT", text="document guidance", published_at=49),
        ])
        for identifier, store, version in [(1, "transcript", "v1"), (2, "external", "old")]:
            client.upsert("test", [models.PointStruct(id=identifier, vector=[1.] + [0.] * 31,
                          payload=dict(store=store, embedding_version=version, ticker="WMT", published_at=100))])
        assert retriever.count_documents(ticker="WMT", since_epoch=50, until_epoch=200) == 2


def test_app_shares_local_qdrant_and_readiness_uses_its_retriever(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, VECTOR_STORE_BACKEND="qdrant", QDRANT_PATH=str(tmp_path),
                        EMBEDDING_PROVIDER="hash", EMBEDDING_DIMENSION=32,
                        EXTERNAL_EMBEDDING_PROVIDER="hash", EXTERNAL_EMBEDDING_DIMENSION=32)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = main.create_app()
    with TestClient(app) as http:
        shared = app.state.evidence_repository.client
        retriever = app.state.analysis_service.external_retriever
        assert app.state.transcript_repository.client is shared
        assert retriever.client is shared
        retriever.upsert_documents([ExternalDocument(doc_id="one", ticker="WMT", text="revenue guidance", published_at=100)])
        response = http.get("/v1/engine/evidence/readiness", params=dict(ticker="WMT", as_of=100, lookback_days=1))
        assert response.status_code == 200
        assert response.json()["document_count"] == 1
        future = http.get("/v1/engine/evidence/readiness", params=dict(ticker="WMT", as_of=99, lookback_days=1))
        assert future.json()["document_count"] == 0
    # Shutdown released the file lock; the database can be reopened.
    with closing(QdrantClient(path=str(tmp_path))) as reopened:
        assert reopened.collection_exists(settings.qdrant_collection_name)
