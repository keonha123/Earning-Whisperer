"""Compatibility endpoints for collectors, web live-room, and desktop callbacks."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from api.analyze_router import enqueue_analysis_request
from core.integration_state import IntegrationStateStore
from models.integration_models import (
    CompanyUniverseBatchRequest,
    DesktopExecutionFeedbackRequest,
    EarningsScheduleBatchRequest,
    IndicatorSnapshotBatchRequest,
    MarketContextSnapshot,
    TranscriptChunkIngestRequest,
)

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])

_integration_state: Optional[IntegrationStateStore] = None


def init_dependencies(integration_state: IntegrationStateStore) -> None:
    global _integration_state
    _integration_state = integration_state


def _require_state() -> IntegrationStateStore:
    if _integration_state is None:
        raise RuntimeError("integration_router dependencies were not initialized")
    return _integration_state


@router.get("/capabilities")
async def capabilities() -> dict:
    state = _require_state()
    return await state.capabilities()


@router.post("/collector/schedules", status_code=202)
async def ingest_schedules(request: EarningsScheduleBatchRequest) -> dict:
    state = _require_state()
    await state.upsert_schedules(request.items)
    return {
        "status": "accepted",
        "accepted_count": len(request.items),
        "tickers": sorted({item.ticker for item in request.items}),
    }


@router.post("/collector/universe", status_code=202)
async def ingest_company_universe(request: CompanyUniverseBatchRequest) -> dict:
    state = _require_state()
    await state.upsert_company_profiles(request.items)
    return {
        "status": "accepted",
        "accepted_count": len(request.items),
        "tickers": sorted({item.ticker for item in request.items}),
    }


@router.post("/collector/indicator-snapshots", status_code=202)
async def ingest_indicator_snapshots(request: IndicatorSnapshotBatchRequest) -> dict:
    state = _require_state()
    for item in request.items:
        await state.upsert_market_data(
            ticker=item.ticker,
            timestamp=item.timestamp,
            market_data=item.market_data,
        )
    return {
        "status": "accepted",
        "accepted_count": len(request.items),
        "tickers": sorted({item.ticker for item in request.items}),
    }


@router.post("/collector/market-context", status_code=202)
async def ingest_market_context(request: MarketContextSnapshot) -> dict:
    state = _require_state()
    await state.set_market_context(request)
    return {"status": "accepted", "timestamp": request.timestamp}


@router.post("/collector/transcript-chunk", status_code=202)
async def ingest_transcript_chunk(
    request: TranscriptChunkIngestRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    return enqueue_analysis_request(request, background_tasks)


@router.post("/desktop/execution-feedback", status_code=202)
async def ingest_execution_feedback(request: DesktopExecutionFeedbackRequest) -> dict:
    state = _require_state()
    await state.record_execution_feedback(request)
    return {
        "status": "accepted",
        "ticker": request.ticker,
        "executed_at": request.executed_at,
        "is_paper": request.is_paper,
    }


@router.get("/live-room/{ticker}")
async def live_room_view(
    ticker: str,
    call_id: Optional[str] = Query(default=None),
    event_id: Optional[str] = Query(default=None),
) -> dict:
    state = _require_state()
    view = await state.get_live_room_view(ticker=ticker.upper(), call_id=call_id, event_id=event_id)
    if view is None:
        raise HTTPException(status_code=404, detail="No live-room analysis is available for this ticker")
    return view.model_dump(exclude_none=True)


@router.get("/collector/state/{ticker}")
async def collector_state(ticker: str) -> dict:
    state = _require_state()
    return await state.get_ticker_snapshot(ticker.upper())

