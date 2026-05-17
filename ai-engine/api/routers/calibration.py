"""Calibration proposal endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

try:
    from api.dependencies import get_calibration_service
    from models.storage_models import CalibrationPromoteRequest, CalibrationResponse, CalibrationRunRequest
except ImportError:  # pragma: no cover
    from ..dependencies import get_calibration_service
    from ...models.storage_models import CalibrationPromoteRequest, CalibrationResponse, CalibrationRunRequest


router = APIRouter(tags=["calibration"])


@router.post("/v1/engine/calibration/run", response_model=CalibrationResponse)
async def run_calibration(payload: CalibrationRunRequest, request: Request) -> CalibrationResponse:
    try:
        result = get_calibration_service(request.app).run(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CalibrationResponse(status="ok", result=result)


@router.get("/v1/engine/calibration/proposals", response_model=CalibrationResponse)
async def list_calibration_proposals(request: Request, strategy_code: str | None = None, limit: int = 20, offset: int = 0) -> CalibrationResponse:
    try:
        result = get_calibration_service(request.app).list_proposals(strategy_code=strategy_code, limit=limit, offset=offset)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CalibrationResponse(status="ok", result=result)


@router.get("/v1/engine/calibration/proposals/{proposal_id}", response_model=CalibrationResponse)
async def get_calibration_proposal(proposal_id: int, request: Request) -> CalibrationResponse:
    try:
        result = get_calibration_service(request.app).get_proposal(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CalibrationResponse(status="ok", result=result)


@router.post("/v1/engine/calibration/proposals/{proposal_id}/promote", response_model=CalibrationResponse)
async def promote_calibration_proposal(proposal_id: int, payload: CalibrationPromoteRequest, request: Request) -> CalibrationResponse:
    try:
        result = get_calibration_service(request.app).promote(proposal_id, actor=payload.actor, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CalibrationResponse(status="ok", result=result)


__all__ = ["router"]
