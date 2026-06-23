"""Live earnings-session orchestration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

try:
    from api.dependencies import get_live_session_service
    from models.live_session_models import LiveEarningsSessionState, LiveSessionListResponse, LiveSessionStartRequest, LiveSessionStatus, LiveTranscriptChunkRequest
except ImportError:  # pragma: no cover
    from ..dependencies import get_live_session_service
    from ...models.live_session_models import LiveEarningsSessionState, LiveSessionListResponse, LiveSessionStartRequest, LiveSessionStatus, LiveTranscriptChunkRequest

router = APIRouter(prefix="/v1/engine/live-sessions", tags=["live-earnings-sessions"])


@router.post("", response_model=LiveEarningsSessionState, status_code=201)
def start_live_session(payload: LiveSessionStartRequest, request: Request) -> LiveEarningsSessionState:
    return get_live_session_service(request.app).start(payload)


@router.get("", response_model=LiveSessionListResponse)
def list_live_sessions(
    request: Request,
    ticker: str | None = None,
    status: LiveSessionStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> LiveSessionListResponse:
    sessions = get_live_session_service(request.app).list(ticker=ticker, status=status, limit=limit)
    return LiveSessionListResponse(sessions=sessions)


@router.get("/{session_id}", response_model=LiveEarningsSessionState)
def get_live_session(session_id: str, request: Request) -> LiveEarningsSessionState:
    try:
        return get_live_session_service(request.app).get(session_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Live earnings session not found.") from exc


@router.post("/{session_id}/chunks", response_model=LiveEarningsSessionState)
async def ingest_live_chunk(session_id: str, payload: LiveTranscriptChunkRequest, request: Request) -> LiveEarningsSessionState:
    try:
        return await get_live_session_service(request.app).ingest_chunk(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Live earnings session not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/finalize", response_model=LiveEarningsSessionState)
async def finalize_live_session(session_id: str, request: Request) -> LiveEarningsSessionState:
    try:
        return await get_live_session_service(request.app).finalize(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Live earnings session not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
