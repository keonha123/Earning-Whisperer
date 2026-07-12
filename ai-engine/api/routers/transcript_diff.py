"""Standalone historical transcript-diff endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_transcript_diff_service
    from models.transcript_diff_models import TranscriptDiffRequest, TranscriptDiffResponse
except ImportError:  # pragma: no cover
    from ..dependencies import get_transcript_diff_service
    from ...models.transcript_diff_models import TranscriptDiffRequest, TranscriptDiffResponse


router = APIRouter(tags=["transcript-diff"])


@router.post("/v1/engine/transcript/diff", response_model=TranscriptDiffResponse)
async def diff_transcript_v1(payload: TranscriptDiffRequest, request: Request) -> TranscriptDiffResponse:
    service = get_transcript_diff_service(request.app)
    result = await service.analyze(
        ticker=payload.ticker,
        current_chunk=payload.current_chunk,
        source_type=payload.source_type,
        request_metadata=payload.request_metadata,
    )
    return TranscriptDiffResponse.model_validate(result or {"available": False, "ticker": payload.ticker.upper(), "items": [], "warnings": ["transcript_diff_not_applicable"]})


@router.post("/api/v1/transcript/diff", response_model=TranscriptDiffResponse)
async def diff_transcript_legacy(payload: TranscriptDiffRequest, request: Request) -> TranscriptDiffResponse:
    return await diff_transcript_v1(payload, request)


__all__ = ["router"]
