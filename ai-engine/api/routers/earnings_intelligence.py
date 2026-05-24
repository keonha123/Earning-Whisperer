"""RAG-backed earnings intelligence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_earnings_intelligence_service
    from models.earnings_intelligence_models import EarningsIntelligenceRequest, EarningsIntelligenceResponse
except ImportError:  # pragma: no cover
    from ..dependencies import get_earnings_intelligence_service
    from ...models.earnings_intelligence_models import EarningsIntelligenceRequest, EarningsIntelligenceResponse


router = APIRouter(tags=["earnings-intelligence"])


@router.post("/v1/engine/earnings/intelligence", response_model=EarningsIntelligenceResponse)
async def analyze_earnings_intelligence_v1(payload: EarningsIntelligenceRequest, request: Request) -> EarningsIntelligenceResponse:
    service = get_earnings_intelligence_service(request.app)
    return await service.analyze(payload)


@router.post("/api/v1/earnings/intelligence", response_model=EarningsIntelligenceResponse)
async def analyze_earnings_intelligence_legacy(payload: EarningsIntelligenceRequest, request: Request) -> EarningsIntelligenceResponse:
    service = get_earnings_intelligence_service(request.app)
    return await service.analyze(payload)


__all__ = ["router"]
