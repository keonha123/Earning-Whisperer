"""Company impact graph, executive profile, and speaker metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_company_intelligence_service
    from models.intelligence_models import CompanyIntelligenceResponse, CompanyIntelligenceUpsertRequest
except ImportError:  # pragma: no cover
    from ..dependencies import get_company_intelligence_service
    from ...models.intelligence_models import CompanyIntelligenceResponse, CompanyIntelligenceUpsertRequest


router = APIRouter(tags=["company-intelligence"])


@router.get("/v1/engine/company-intelligence/{ticker}", response_model=CompanyIntelligenceResponse)
def get_company_intelligence(ticker: str, request: Request) -> CompanyIntelligenceResponse:
    return get_company_intelligence_service(request.app).get(ticker)


@router.post("/v1/engine/company-intelligence/upsert", response_model=CompanyIntelligenceResponse)
def upsert_company_intelligence(payload: CompanyIntelligenceUpsertRequest, request: Request) -> CompanyIntelligenceResponse:
    return get_company_intelligence_service(request.app).upsert(payload)


__all__ = ["router"]
