"""Collector integration endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

try:
    from core.external_retriever import external_retriever
    from models.ingestion_models import (
        CollectorNewsIngestRequest,
        CollectorNewsIngestResponse,
        EarningsTranscriptIngestRequest,
        EarningsTranscriptIngestResponse,
    )
except ImportError:  # pragma: no cover
    from ...core.external_retriever import external_retriever
    from ...models.ingestion_models import (
        CollectorNewsIngestRequest,
        CollectorNewsIngestResponse,
        EarningsTranscriptIngestRequest,
        EarningsTranscriptIngestResponse,
    )


class EvidenceReadinessResponse(BaseModel):
    """근거 저장소 준비 상태.

    시연 직전 확인용이다. 근거가 하나도 없는 상태로 어닝콜을 재생하면 화면에는
    "근거 부족" 만 줄줄이 뜨는데, 그것이 정말 근거 없는 주장인지 저장소가 빈 것인지
    구별할 방법이 없다. 백엔드가 재생 시작 전에 이 값을 확인해 경고를 띄운다.
    """

    ticker: str
    document_count: int = Field(description="검색 창 안에 있는 이 종목의 근거 문서 수")
    lookback_days: int
    as_of_epoch: int
    ready: bool = Field(description="근거가 최소 기준을 넘는지")
    minimum_expected: int


#: 이 아래면 팩트체크가 사실상 전부 근거 부족으로 떨어진다. 경험값이다.
MINIMUM_EXPECTED_DOCUMENTS = 20


router = APIRouter(tags=["integration"])


@router.get("/v1/engine/evidence/readiness", response_model=EvidenceReadinessResponse)
async def evidence_readiness(
    request: Request,
    ticker: str = Query(..., min_length=1),
    as_of: int | None = Query(None, description="기준 시각(epoch seconds). 과거 콜 재생 시 그 콜의 시각."),
    lookback_days: int | None = Query(None, ge=1),
) -> EvidenceReadinessResponse:
    settings = request.app.state.settings
    window_days = lookback_days or settings.fact_check_news_lookback_days
    as_of_epoch = int(as_of) if as_of else int(datetime.now(UTC).timestamp())
    since_epoch = as_of_epoch - int(timedelta(days=window_days).total_seconds())

    count = external_retriever.count_documents(ticker=ticker.upper(), since_epoch=since_epoch)
    return EvidenceReadinessResponse(
        ticker=ticker.upper(),
        document_count=count,
        lookback_days=window_days,
        as_of_epoch=as_of_epoch,
        ready=count >= MINIMUM_EXPECTED_DOCUMENTS,
        minimum_expected=MINIMUM_EXPECTED_DOCUMENTS,
    )


@router.post("/api/v1/integration/collector/earnings-transcripts", response_model=EarningsTranscriptIngestResponse)
async def ingest_earnings_transcripts(payload: EarningsTranscriptIngestRequest, request: Request) -> EarningsTranscriptIngestResponse:
    return request.app.state.transcript_ingestion_service.ingest(payload.items)


@router.post("/api/v1/integration/collector/news", response_model=CollectorNewsIngestResponse)
async def ingest_collector_news(payload: CollectorNewsIngestRequest, request: Request) -> CollectorNewsIngestResponse:
    return request.app.state.news_ingestion_service.ingest(payload.items)


__all__ = ["router"]
