"""Regression comparison and reporting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

try:
    from api.dependencies import get_regression_service
    from models.storage_models import RegressionCompareRequest, RegressionReportListResponse, RegressionReportResponse
except ImportError:  # pragma: no cover
    from ..dependencies import get_regression_service
    from ...models.storage_models import RegressionCompareRequest, RegressionReportListResponse, RegressionReportResponse


router = APIRouter(tags=["regression"])


@router.post("/v1/engine/regression/compare", response_model=RegressionReportResponse)
async def compare_regression(payload: RegressionCompareRequest, request: Request) -> RegressionReportResponse:
    try:
        result = get_regression_service(request.app).compare(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RegressionReportResponse(status="ok", result=result)


@router.get("/v1/engine/regression/reports", response_model=RegressionReportListResponse)
async def list_regression_reports(
    request: Request,
    strategy_code: str | None = None,
    suite_name: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> RegressionReportListResponse:
    try:
        result = get_regression_service(request.app).list_reports(
            strategy_code=strategy_code,
            suite_name=suite_name,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RegressionReportListResponse(status="ok", result=result)


@router.get("/v1/engine/regression/reports/{report_id}", response_model=RegressionReportResponse)
async def get_regression_report(report_id: str, request: Request) -> RegressionReportResponse:
    try:
        result = get_regression_service(request.app).get_report(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RegressionReportResponse(status="ok", result=result)


__all__ = ["router"]
