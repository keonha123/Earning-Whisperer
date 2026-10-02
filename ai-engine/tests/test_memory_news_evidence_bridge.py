from fastapi.testclient import TestClient

import main
from config import Settings


def test_collector_news_visible_to_generic_evidence_search_with_asof(monkeypatch):
    settings = Settings(_env_file=None, VECTOR_STORE_BACKEND="memory")
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = main.create_app()
    client = TestClient(app)
    items = [
        dict(provider="test", provider_id=key, ticker=ticker, headline="Revenue guidance raised",
             content="Revenue guidance raised with stronger margins", published_at=date)
        for key, ticker, date in [("prior", "WMT", 100), ("future", "WMT", 201),
                                 ("unknown", "WMT", None), ("other", "NVDA", 100)]
    ]
    response = client.post("/api/v1/integration/collector/news", json={"items": items})
    assert response.status_code == 200
    assert response.json()["accepted_count"] == 4
    response = client.post("/v1/engine/evidence/search", json={
        "ticker": "WMT", "query": "Revenue guidance raised", "top_k": 1,
        "metadata": {"as_of": 200},
    })
    assert response.status_code == 200
    result = response.json()
    assert result["backend"] == "LOCAL_SPARSE"
    assert [item["document_id"] for item in result["evidence"]] == ["test:WMT:prior"]
    # Dates alone collapse both 100 and 201 seconds onto 1970-01-01; QA must
    # retain the original source timestamp for same-day cutoff verification.
    assert result["evidence"][0]["metadata"]["published_at_epoch"] == 100
    assert result["missing_evidence"] is False
    before = client.post("/v1/engine/evidence/search", json={
        "ticker": "WMT", "query": "Revenue guidance raised", "metadata": {"as_of": 99},
    })
    assert before.json()["evidence"] == []
    source_filtered = client.post("/v1/engine/evidence/search", json={
        "ticker": "WMT", "query": "Revenue guidance raised", "source_types": ["FILING"],
    })
    assert source_filtered.json()["evidence"] == []
    # A separate app must not see the first application's in-memory ingestion.
    isolated = TestClient(main.create_app()).post("/v1/engine/evidence/search", json={
        "ticker": "WMT", "query": "Revenue guidance raised",
    })
    assert isolated.json()["evidence"] == []


def test_external_citation_unknown_date_cannot_inherit_metadata_epoch():
    from core.external_retriever import ExternalRetrievedDocument
    from services.evidence_retrieval_service import EvidenceRetrievalService

    item = ExternalRetrievedDocument(doc_id="unknown", text="Revenue guidance", score=0.8,
                                     published_at=0, metadata={"published_at_epoch": 100})
    citation = EvidenceRetrievalService._external_citation(item, ticker="WMT")
    assert citation.metadata["published_at_epoch"] is None
