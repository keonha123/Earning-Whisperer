from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.integration import router
from models.ingestion_models import CollectorNewsIngestItem
from services.news_ingestion_service import NewsIngestionService


class FakeRetriever:
    def __init__(self) -> None:
        self.documents = []

    def upsert_documents(self, documents) -> None:
        self.documents.extend(documents)


def test_news_ingestion_maps_finnhub_item_to_external_document() -> None:
    retriever = FakeRetriever()
    service = NewsIngestionService(retriever)

    response = service.ingest(
        [
            CollectorNewsIngestItem(
                provider="finnhub",
                provider_id="12345",
                ticker="nvda",
                headline="NVIDIA raises outlook on AI demand",
                summary="Data center revenue accelerated.",
                url="https://example.test/news/12345",
                source="Reuters",
                published_at=1_700_000_000,
                metadata={"category": "company news", "related": "NVDA"},
            )
        ]
    )

    assert response.accepted_count == 1
    assert response.document_ids == ["finnhub:NVDA:12345"]
    doc = retriever.documents[0]
    assert doc.doc_id == "finnhub:NVDA:12345"
    assert doc.ticker == "NVDA"
    assert doc.source_type == "news"
    assert doc.title == "NVIDIA raises outlook on AI demand"
    assert "Data center revenue accelerated" in doc.text
    assert doc.metadata["provider"] == "finnhub"
    assert doc.metadata["source"] == "Reuters"


def test_news_ingestion_uses_full_content_instead_of_summary_when_available() -> None:
    retriever = FakeRetriever()
    service = NewsIngestionService(retriever)

    response = service.ingest(
        [
            CollectorNewsIngestItem(
                provider="finnhub",
                provider_id="full-text",
                ticker="nvda",
                headline="NVIDIA headline remains the title",
                summary="This summary should not be embedded.",
                content="This is the extracted full article body used for embedding.",
                url="https://example.test/news/full-text",
                source="Reuters",
                published_at=1_700_000_000,
                metadata={"content_extraction_status": "success", "content_length": 58},
            )
        ]
    )

    assert response.accepted_count == 1
    doc = retriever.documents[0]
    assert doc.title == "NVIDIA headline remains the title"
    assert doc.text == "This is the extracted full article body used for embedding."
    assert "This summary should not be embedded" not in doc.text
    assert doc.metadata["content_extraction_status"] == "success"


def test_collector_news_endpoint_ingests_payload() -> None:
    retriever = FakeRetriever()
    app = FastAPI()
    app.include_router(router)
    app.state.news_ingestion_service = NewsIngestionService(retriever)
    client = TestClient(app)

    response = client.post(
        "/api/v1/integration/collector/news",
        json={
            "items": [
                {
                    "provider": "finnhub",
                    "provider_id": "abc",
                    "ticker": "MSFT",
                    "headline": "Microsoft cloud demand improves",
                    "summary": "Azure AI workloads remained strong.",
                    "url": "https://example.test/msft",
                    "source": "Dow Jones",
                    "published_at": 1_700_000_001,
                    "metadata": {"category": "company news"},
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["accepted_count"] == 1
    assert payload["document_ids"] == ["finnhub:MSFT:abc"]
    assert retriever.documents[0].ticker == "MSFT"
