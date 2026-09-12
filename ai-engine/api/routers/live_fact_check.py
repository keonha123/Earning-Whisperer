"""Live earnings-call fact-check endpoint.

어닝콜이 진행되는 동안 확정된 문장을 하나씩 받아 3문장 단위로 검증한다.
`/v1/engine/fact-check` (검색 기반 단발 검증) 와는 다른 경로다 — 이쪽은
LLM 2패스(주장 추출 → 뉴스 근거 대조)를 거치며 문장 버퍼 상태를 유지한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_live_news_fact_check_service
    from models.live_fact_check_models import (
        LiveFactCheckBatchResponse,
        LiveFactCheckSentenceRequest,
    )
except ImportError:  # pragma: no cover
    from ..dependencies import get_live_news_fact_check_service
    from ...models.live_fact_check_models import (
        LiveFactCheckBatchResponse,
        LiveFactCheckSentenceRequest,
    )


router = APIRouter(tags=["live-fact-check"])


@router.post("/v1/engine/live-fact-check/sentence", response_model=LiveFactCheckBatchResponse)
async def submit_live_sentence(
    payload: LiveFactCheckSentenceRequest,
    request: Request,
) -> LiveFactCheckBatchResponse:
    """확정된 어닝콜 문장 1개를 제출한다.

    3문장이 모일 때까지는 `status=BUFFERING` 으로 즉시 반환하고, 3번째 문장에서
    비로소 LLM 검증이 돌아 `status=COMPLETED` + `claims[]` 를 돌려준다.
    버퍼는 ticker 별로 유지되며 `sentence_sequence=0` 재인입 시 초기화된다.

    HTTP 상태는 항상 200 이다. 중복/역행 시퀀스(`REJECTED`)나 3문장 미만 세션 종료
    (`DISCARDED`) 도 예외가 아니라 정상 흐름의 일부이므로 본문 `status` 로 구분한다.
    호출자는 반드시 `status` 를 분기해야 한다.
    """
    service = get_live_news_fact_check_service(request.app)
    return await service.submit_sentence(payload)


__all__ = ["router"]
