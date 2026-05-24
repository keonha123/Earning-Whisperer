"""Evidence retrieval, live fact-check, impact-chain, and exit-plan endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_evidence_service
    from models.evidence_models import (
        ClaimDiffRequest,
        ClaimDiffResponse,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        FactCheckRequest,
        FactCheckResponse,
        ImpactChainRequest,
        ImpactChainResponse,
        ImpactDirection,
        OmissionAnalysisRequest,
        OmissionAnalysisResponse,
        TradeExitPlanRequest,
        TradeExitPlanResponse,
    )
except ImportError:  # pragma: no cover
    from ..dependencies import get_evidence_service
    from ...models.evidence_models import (
        ClaimDiffRequest,
        ClaimDiffResponse,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        FactCheckRequest,
        FactCheckResponse,
        ImpactChainRequest,
        ImpactChainResponse,
        ImpactDirection,
        OmissionAnalysisRequest,
        OmissionAnalysisResponse,
        TradeExitPlanRequest,
        TradeExitPlanResponse,
    )


router = APIRouter(tags=["evidence"])


@router.post("/v1/engine/evidence/search", response_model=EvidenceRetrievalResult)
async def search_evidence(payload: EvidenceRetrievalRequest, request: Request) -> EvidenceRetrievalResult:
    return get_evidence_service(request.app).retrieve(payload)


@router.post("/v1/engine/fact-check", response_model=FactCheckResponse)
async def fact_check(payload: FactCheckRequest, request: Request) -> FactCheckResponse:
    return get_evidence_service(request.app).fact_check(payload)


@router.post("/v1/engine/claim-diff", response_model=ClaimDiffResponse)
async def claim_diff(payload: ClaimDiffRequest, request: Request) -> ClaimDiffResponse:
    return get_evidence_service(request.app).claim_diff(payload)


@router.post("/v1/engine/omission/analyze", response_model=OmissionAnalysisResponse)
async def analyze_omission(payload: OmissionAnalysisRequest, request: Request) -> OmissionAnalysisResponse:
    return get_evidence_service(request.app).analyze_omission(payload)


@router.get("/v1/engine/impact-chain/{ticker}", response_model=ImpactChainResponse)
async def get_impact_chain(
    ticker: str,
    request: Request,
    source_direction: ImpactDirection = ImpactDirection.NEUTRAL,
    confidence: float = 0.65,
    top_k: int = 10,
) -> ImpactChainResponse:
    payload = ImpactChainRequest(
        source_ticker=ticker,
        source_direction=source_direction,
        confidence=max(0.0, min(1.0, confidence)),
        top_k=top_k,
    )
    return get_evidence_service(request.app).impact_chain(payload)


@router.post("/v1/engine/impact-chain/analyze", response_model=ImpactChainResponse)
async def analyze_impact_chain(payload: ImpactChainRequest, request: Request) -> ImpactChainResponse:
    return get_evidence_service(request.app).impact_chain(payload)


@router.post("/v1/engine/trade-exits/generate", response_model=TradeExitPlanResponse)
async def generate_trade_exits(payload: TradeExitPlanRequest, request: Request) -> TradeExitPlanResponse:
    return get_evidence_service(request.app).generate_trade_exit_plan(payload)


__all__ = ["router"]
