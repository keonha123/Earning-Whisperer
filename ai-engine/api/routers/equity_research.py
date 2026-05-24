"""Frontend-facing equity research report endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_equity_report_service
    from models.equity_report_models import EquityReportRequest, EquityReportResponse
except ImportError:  # pragma: no cover
    from ..dependencies import get_equity_report_service
    from ...models.equity_report_models import EquityReportRequest, EquityReportResponse


router = APIRouter(tags=["equity-research"])


@router.post("/v1/research/equity-report", response_model=EquityReportResponse)
async def generate_equity_report_v1(payload: EquityReportRequest, request: Request) -> EquityReportResponse:
    service = get_equity_report_service(request.app)
    return await service.generate_report(payload)


@router.post("/api/v1/research/equity-report", response_model=EquityReportResponse)
async def generate_equity_report_legacy_api(payload: EquityReportRequest, request: Request) -> EquityReportResponse:
    service = get_equity_report_service(request.app)
    return await service.generate_report(payload)


__all__ = ["router"]
