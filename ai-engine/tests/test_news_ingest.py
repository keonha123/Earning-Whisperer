from __future__ import annotations

import pytest

from api import integration_router
from models.integration_models import NewsBatchRequest, NewsItem


class _FakeExternalRetriever:
    def __init__(self) -> None:
        self.documents = []

    def upsert_documents(self, documents):
        self.documents.extend(documents)


@pytest.mark.asyncio
async def test_ingest_news_converts_finnhub_items_to_external_documents(monkeypatch):
    fake_retriever = _FakeExternalRetriever()
    monkeypatch.setattr(integration_router, "external_retriever", fake_retriever)

    response = await integration_router.ingest_news(
        NewsBatchRequest(
            items=[
                NewsItem(
                    provider="finnhub",
                    provider_id="123",
                    ticker="nvda",
                    headline="NVIDIA announces new AI platform",
                    summary="The company said demand remains strong.",
                    url="https://example.com/news/123",
                    source="Reuters",
                    published_at=1741826900,
                    metadata={"category": "company", "related": "NVDA"},
                )
            ]
        )
    )

    assert response == {"status": "accepted", "accepted_count": 1, "tickers": ["NVDA"]}
    assert len(fake_retriever.documents) == 1

    document = fake_retriever.documents[0]
    assert document.doc_id == "finnhub-news:NVDA:123"
    assert document.ticker == "NVDA"
    assert document.source_type == "news"
    assert document.published_at == 1741826900
    assert document.url == "https://example.com/news/123"
    assert "NVIDIA announces new AI platform" in document.text
    assert "demand remains strong" in document.text
    assert document.metadata["provider"] == "finnhub"
    assert document.metadata["provider_id"] == "123"
    assert document.metadata["source"] == "Reuters"
