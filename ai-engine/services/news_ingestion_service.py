from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

try:
    from core.external_retriever import ExternalDocument
    from models.ingestion_models import CollectorNewsIngestItem, CollectorNewsIngestResponse
except ImportError:  # pragma: no cover
    from ..core.external_retriever import ExternalDocument
    from ..models.ingestion_models import CollectorNewsIngestItem, CollectorNewsIngestResponse


class NewsIngestionService:
    def __init__(self, retriever) -> None:
        self.retriever = retriever

    def ingest(self, items: Iterable[CollectorNewsIngestItem]) -> CollectorNewsIngestResponse:
        documents: list[ExternalDocument] = []
        warnings: list[str] = []
        skipped = 0
        document_ids: list[str] = []
        for item in items:
            headline = " ".join(str(item.headline or "").split())
            summary = " ".join(str(item.summary or "").split())
            content = " ".join(str(item.content or "").split())
            text = content or " ".join(part for part in [headline, summary] if part)
            if not text:
                skipped += 1
                warnings.append(f"empty_news_text:{item.ticker}:{item.provider_id}")
                continue
            doc_id = f"{item.provider}:{item.ticker}:{item.provider_id}"
            document_ids.append(doc_id)
            documents.append(
                ExternalDocument(
                    doc_id=doc_id,
                    ticker=item.ticker,
                    text=text,
                    title=headline,
                    published_at=_published_at_epoch(item.published_at),
                    source_type="news",
                    url=item.url,
                    form_type="",
                    metadata={
                        **dict(item.metadata or {}),
                        "provider": item.provider,
                        "provider_id": item.provider_id,
                        "source": item.source,
                        "collector": "finnhub_company_news",
                    },
                )
            )
        if documents:
            self.retriever.upsert_documents(documents)
        return CollectorNewsIngestResponse(
            status="ok" if documents or skipped else "skipped",
            accepted_count=len(documents),
            skipped_count=skipped,
            document_ids=document_ids,
            warnings=warnings,
        )


def _published_at_epoch(value) -> int:
    if value is None:
        return 0
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    return 0


__all__ = ["NewsIngestionService"]
