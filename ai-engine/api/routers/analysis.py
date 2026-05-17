"""Analysis and persistence endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

try:
    from api.dependencies import get_dispatch_analysis, get_persist_envelope
    from models.request_models import AnalyzeRequest
    from models.storage_models import AnalyzeAndPersistResponse, PersistEnvelopeResponse
except ImportError:  # pragma: no cover
    from ..dependencies import get_dispatch_analysis, get_persist_envelope
    from ...models.request_models import AnalyzeRequest
    from ...models.storage_models import AnalyzeAndPersistResponse, PersistEnvelopeResponse


router = APIRouter(tags=["analysis"])


@router.post("/v1/engine/analyze")
async def analyze_v1(payload: AnalyzeRequest, request: Request) -> dict[str, Any]:
    dispatcher = get_dispatch_analysis(request.app)
    return await dispatcher(payload)


@router.post("/analyze")
async def analyze(payload: AnalyzeRequest, request: Request) -> dict[str, Any]:
    dispatcher = get_dispatch_analysis(request.app)
    return await dispatcher(payload)


@router.post("/v1/engine/events/persist", response_model=PersistEnvelopeResponse)
async def persist_engine_event(envelope: dict[str, Any], request: Request) -> PersistEnvelopeResponse:
    persist = get_persist_envelope(request.app)
    return persist(envelope)


@router.post("/v1/engine/analyze-and-persist", response_model=AnalyzeAndPersistResponse)
async def analyze_and_persist(payload: AnalyzeRequest, request: Request) -> AnalyzeAndPersistResponse:
    dispatcher = get_dispatch_analysis(request.app)
    envelope = await dispatcher(payload)
    try:
        persisted = get_persist_envelope(request.app)(envelope)
    except HTTPException:
        raise
    return AnalyzeAndPersistResponse(
        status="ok",
        persisted=persisted.persisted,
        event_id=persisted.event_id,
        run_id=persisted.run_id,
        row_counts=persisted.row_counts,
        envelope=envelope,
    )


__all__ = ["router"]
