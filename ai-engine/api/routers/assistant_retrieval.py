"""logothea-assistant 근거 조회 엔드포인트 (#112).

기존 검색기와 직전 콜 저장소를 그대로 쓰고, 질문 시점(as_of) 조건만 덧붙인다.
기존 /v1/engine/evidence/search 와 달리 published_at 상한을 보장한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request

try:
    from models.assistant_retrieval_models import (
        NewsSearchHit,
        NewsSearchRequest,
        NewsSearchResponse,
        PriorCallStatement,
        PriorCallStatementsResponse,
    )
except ImportError:  # pragma: no cover
    from ...models.assistant_retrieval_models import (
        NewsSearchHit,
        NewsSearchRequest,
        NewsSearchResponse,
        PriorCallStatement,
        PriorCallStatementsResponse,
    )

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assistant-retrieval"])

SNIPPET_CHARS = 600


@router.post("/v1/engine/assistant/news-search", response_model=NewsSearchResponse)
def search_news(payload: NewsSearchRequest, request: Request) -> NewsSearchResponse:
    retriever = request.app.state.analysis_service.external_retriever
    try:
        documents = retriever.retrieve(
            query=payload.query,
            ticker=payload.ticker,
            chunk_timestamp=payload.as_of_epoch,
            lookback_days=payload.lookback_days,
            limit=payload.top_k,
        )
    except Exception:
        logger.exception("assistant 뉴스 검색 실패 - ticker=%s", payload.ticker)
        return NewsSearchResponse(ticker=payload.ticker, as_of_epoch=payload.as_of_epoch, warnings=["news_search_failed"])
    # 검색기 백엔드(memory 등)가 시점 상한을 지키지 않아도 계약은 여기서 보장한다.
    hits = [_hit(doc) for doc in documents if 0 < int(doc.published_at or 0) <= payload.as_of_epoch]
    return NewsSearchResponse(ticker=payload.ticker, as_of_epoch=payload.as_of_epoch, hits=hits[: payload.top_k])


@router.get("/v1/engine/assistant/prior-call-statements", response_model=PriorCallStatementsResponse)
def prior_call_statements(
    request: Request,
    ticker: str = Query(min_length=1),
    before_epoch: int = Query(gt=0),
) -> PriorCallStatementsResponse:
    symbol = ticker.strip().upper()
    repository = request.app.state.transcript_repository
    if not hasattr(repository, "find_latest_transcript"):
        return PriorCallStatementsResponse(available=False, ticker=symbol, warnings=["prior_call_lookup_unsupported"])
    latest = repository.find_latest_transcript(ticker=symbol, before=datetime.fromtimestamp(before_epoch, tz=UTC))
    if not latest:
        return PriorCallStatementsResponse(available=False, ticker=symbol, warnings=["prior_call_not_found"])
    document_id = str(latest.get("document_id") or "")
    statements = sorted(request.app.state.transcript_statement_service.list(document_id), key=lambda s: s.order)
    return PriorCallStatementsResponse(
        available=True,
        ticker=symbol,
        document_id=document_id,
        fiscal_quarter=latest.get("fiscal_quarter"),
        published_at_epoch=int(latest.get("published_at_epoch") or 0) or None,
        statements=[
            PriorCallStatement(statement_id=s.statement_id, order=s.order, topic=s.topic, speaker=s.speaker, text=s.text)
            for s in statements
        ],
        warnings=[] if statements else ["key_statements_not_found"],
    )


def _hit(document) -> NewsSearchHit:
    metadata = document.metadata or {}
    source = str(metadata.get("source") or metadata.get("publisher") or urlparse(document.url or "").netloc or "")
    return NewsSearchHit(
        doc_id=document.doc_id,
        title=document.title or "",
        source=source,
        url=document.url or "",
        published_at=int(document.published_at or 0),
        snippet=(document.text or "")[:SNIPPET_CHARS],
        score=round(float(document.score or 0.0), 4),
    )


__all__ = ["router"]
