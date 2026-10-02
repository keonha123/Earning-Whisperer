"""어닝콜 세그먼트 한국어 번역 엔드포인트 (#110)."""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_transcript_translation_service
    from models.transcript_translation_models import TranscriptTranslateRequest, TranscriptTranslateResponse
except ImportError:  # pragma: no cover
    from ..dependencies import get_transcript_translation_service
    from ...models.transcript_translation_models import TranscriptTranslateRequest, TranscriptTranslateResponse


router = APIRouter(tags=["transcript-translation"])


@router.post("/v1/engine/transcript/translate", response_model=TranscriptTranslateResponse)
async def translate_transcript(payload: TranscriptTranslateRequest, request: Request) -> TranscriptTranslateResponse:
    """세그먼트 1개를 한국어로 번역한다.

    HTTP 상태는 항상 200 이다. LLM 실패 · 시간 초과 · 한국어가 아닌 응답은
    `available=false` 와 `warnings` 로 알린다. 호출자는 `available` 을 분기해야 한다.
    """
    service = get_transcript_translation_service(request.app)
    return await service.translate(payload)


__all__ = ["router"]
