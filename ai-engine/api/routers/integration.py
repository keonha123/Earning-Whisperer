"""Collector integration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from models.ingestion_models import (
        CollectorNewsIngestRequest,
        CollectorNewsIngestResponse,
        EarningsTranscriptIngestRequest,
        EarningsTranscriptIngestResponse,
    )
except ImportError:  # pragma: no cover
    from ...models.ingestion_models import (
        CollectorNewsIngestRequest,
        CollectorNewsIngestResponse,
        EarningsTranscriptIngestRequest,
        EarningsTranscriptIngestResponse,
    )


router = APIRouter(tags=["integration"])


@router.post("/api/v1/integration/collector/earnings-transcripts", response_model=EarningsTranscriptIngestResponse)
async def ingest_earnings_transcripts(payload: EarningsTranscriptIngestRequest, request: Request) -> EarningsTranscriptIngestResponse:
    return request.app.state.transcript_ingestion_service.ingest(payload.items)


@router.post("/api/v1/integration/collector/news", response_model=CollectorNewsIngestResponse)
async def ingest_collector_news(payload: CollectorNewsIngestRequest, request: Request) -> CollectorNewsIngestResponse:
    return request.app.state.news_ingestion_service.ingest(payload.items)


__all__ = ["router"]
