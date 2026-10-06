"""근거 수집과 조립.

모든 근거는 질문 시점(as_of)까지로 제한한다. backend·ai-engine 도 같은 조건으로 거르지만,
어느 한쪽이 실수해도 미래 정보가 답에 섞이지 않도록 여기서 한 번 더 거른다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from assistant.clients import SourceUnavailable
from assistant.schemas import AskRequest

logger = logging.getLogger(__name__)

# 직전 콜 조회 상한을 질문 시점보다 7일 앞으로 둔다. 진행 중인 콜 자신의 전사본이 이미 적재되어 있어도
# 직전 콜로 잡히지 않게 하기 위해서다. 분기 콜 간격은 약 90일이라 7일 앞당겨도 직전 콜은 그대로 잡힌다.
PRIOR_CALL_GAP_SECONDS = 7 * 24 * 3600
# 다음 일정이 질문 시점과 이틀 안이면 이번 콜의 일정으로 본다.
THIS_CALL_WINDOW_SECONDS = 2 * 24 * 3600

_PRIOR_FAILURE_WARNINGS = {"prior_call_lookup_failed", "prior_call_lookup_unsupported"}
_FAILED = object()

EvidenceType = Literal["segment", "news", "prior_statement", "estimate"]


@dataclass(frozen=True)
class Evidence:
    marker: str
    type: EvidenceType
    ref: str
    text: str
    title: str | None = None
    source: str | None = None
    published_at: int | None = None
    start_ms: int | None = None
    speaker: str | None = None


@dataclass
class BaseSources:
    segments: dict[str, Any]
    estimates: dict[str, Any] | None
    prior: dict[str, Any] | None
    missing_sources: list[str]


@dataclass
class ContextBundle:
    segments: list[Evidence]
    news: list[Evidence]
    prior: list[Evidence]
    estimates: list[Evidence]
    as_of_sequence: int
    anchor_sequence: int | None
    missing_sources: list[str]

    @property
    def evidence(self) -> dict[str, Evidence]:
        return {item.marker: item for item in [*self.segments, *self.news, *self.prior, *self.estimates]}


class ContextError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ContextAssembler:
    def __init__(self, backend: Any, engine: Any, *, timeout_seconds: float, news_top_k: int,
                 news_lookback_days: int) -> None:
        self._backend = backend
        self._engine = engine
        self._timeout = timeout_seconds
        self._news_top_k = news_top_k
        self._news_lookback_days = news_lookback_days

    async def gather_base(self, request: AskRequest) -> BaseSources:
        segments, estimates, prior = await asyncio.gather(
            self._bounded(self._backend.segments(call_id=request.call_id, until_sequence=request.as_of_sequence)),
            self._bounded(self._backend.estimates(ticker=request.ticker, as_of_epoch=request.as_of_epoch)),
            self._bounded(self._engine.prior_call_statements(
                ticker=request.ticker, before_epoch=request.as_of_epoch - PRIOR_CALL_GAP_SECONDS)),
        )
        if segments is _FAILED:
            raise ContextError("context_unavailable")
        if segments is None or not segments.get("segments"):
            raise ContextError("segments_not_found")

        missing: list[str] = []
        if estimates is _FAILED:
            missing.append("estimates")
            estimates = None
        if prior is _FAILED or (prior and _PRIOR_FAILURE_WARNINGS & set(prior.get("warnings", []))):
            missing.append("prior_call")
            prior = None
        return BaseSources(segments=segments, estimates=estimates, prior=prior, missing_sources=missing)

    async def gather_news(self, request: AskRequest, query: str) -> tuple[list[dict[str, Any]], list[str]]:
        if not query.strip():
            return [], []
        result = await self._bounded(self._engine.news_search(
            ticker=request.ticker, query=query, as_of_epoch=request.as_of_epoch,
            lookback_days=self._news_lookback_days, top_k=self._news_top_k))
        if result is _FAILED:
            return [], ["news"]
        missing = ["news"] if "news_search_failed" in result.get("warnings", []) else []
        return result.get("hits", []), missing

    def build(self, request: AskRequest, base: BaseSources, news_hits: list[dict[str, Any]],
              news_missing: list[str]) -> ContextBundle:
        segments = _segment_evidence(base.segments, request.as_of_sequence)
        if not segments:
            raise ContextError("segments_not_found")
        sequences = [int(item.ref) for item in segments]
        missing = [*base.missing_sources, *news_missing]
        if any(later - earlier > 1 for earlier, later in zip(sequences, sequences[1:])):
            missing.append("segments_incomplete")
        anchor = request.anchor_sequence if request.anchor_sequence in sequences else None
        return ContextBundle(
            segments=segments,
            news=_news_evidence(news_hits, request.as_of_epoch),
            prior=_prior_evidence(base.prior),
            estimates=_estimate_evidence(base.estimates, request.as_of_epoch),
            as_of_sequence=sequences[-1],
            anchor_sequence=anchor,
            missing_sources=missing,
        )

    async def _bounded(self, awaitable: Awaitable[Any]) -> Any:
        try:
            return await asyncio.wait_for(awaitable, self._timeout)
        except (TimeoutError, SourceUnavailable) as exc:
            logger.warning("근거 정보원을 읽지 못했습니다: %r", exc)
            return _FAILED


def _segment_evidence(payload: dict[str, Any], as_of_sequence: int) -> list[Evidence]:
    rows = sorted((row for row in payload.get("segments", []) if int(row["sequence"]) <= as_of_sequence),
                  key=lambda row: int(row["sequence"]))
    result: list[Evidence] = []
    seen: set[int] = set()
    for row in rows:
        sequence = int(row["sequence"])
        if sequence in seen:
            continue
        seen.add(sequence)
        result.append(Evidence(marker=f"S{sequence}", type="segment", ref=str(sequence), text=row.get("text") or "",
                               speaker=row.get("speaker"), start_ms=row.get("start_ms"),
                               published_at=row.get("timestamp")))
    return result


def _news_evidence(hits: list[dict[str, Any]], as_of_epoch: int) -> list[Evidence]:
    result: list[Evidence] = []
    for hit in hits:
        published = int(hit.get("published_at") or 0)
        if not 0 < published <= as_of_epoch:
            continue
        title = hit.get("title") or ""
        result.append(Evidence(marker=f"N{len(result) + 1}", type="news", ref=str(hit.get("doc_id") or ""),
                               text=f"{title}\n{hit.get('snippet') or ''}".strip(), title=title or None,
                               source=hit.get("source"), published_at=published))
    return result


def _prior_evidence(payload: dict[str, Any] | None) -> list[Evidence]:
    if not payload or not payload.get("available"):
        return []
    statements = sorted(payload.get("statements", []), key=lambda row: row.get("order") or 0)
    return [
        Evidence(marker=f"P{index}", type="prior_statement", ref=str(row.get("statement_id") or ""),
                 text=row.get("text") or "", title=payload.get("fiscal_quarter"), speaker=row.get("speaker"),
                 published_at=payload.get("published_at_epoch"))
        for index, row in enumerate(statements, start=1)
    ]


def _estimate_evidence(payload: dict[str, Any] | None, as_of_epoch: int) -> list[Evidence]:
    if not payload:
        return []
    result: list[Evidence] = []
    upcoming = payload.get("upcoming")
    if upcoming:
        scheduled = _epoch(upcoming.get("scheduled_at"))
        is_this_call = scheduled is not None and abs(scheduled - as_of_epoch) <= THIS_CALL_WINDOW_SECONDS
        label = "이번 실적 발표 시장 예상" if is_this_call else "다음 실적 발표 시장 예상"
        result.append(Evidence(
            marker="E1", type="estimate", ref="upcoming", title=label,
            text=(f"{label}(예정 {_date(scheduled)}): EPS 추정 {_usd(upcoming.get('eps_estimate'))}, "
                  f"매출 추정 {_usd(upcoming.get('revenue_estimate'))}")))
    for row in payload.get("recent_results", []):
        label = row.get("fiscal_period_label") or "분기"
        result.append(Evidence(
            marker=f"E{len(result) + 1}", type="estimate", ref=f"result:{row.get('announced_at')}",
            title=f"{label} 실적",
            text=(f"{label} 실적(발표 {_date(_epoch(row.get('announced_at')))}): "
                  f"EPS 추정 {_usd(row.get('eps_estimate'))}, 실제 {_usd(row.get('eps_actual'))}, "
                  f"서프라이즈 {_pct(row.get('surprise_percent'))}, "
                  f"발표 후 7일 주가 반응 {_pct(row.get('price_reaction_percent'))}")))
    return result


def _epoch(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value)
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())


def _date(epoch: int | None) -> str:
    return "날짜 미상" if epoch is None else datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")


def _usd(value: Any) -> str:
    if value is None:
        return "자료 없음"
    amount = float(value)
    if abs(amount) >= 1e9:
        return f"${amount / 1e9:.2f} billion"
    if abs(amount) >= 1e6:
        return f"${amount / 1e6:.2f} million"
    return f"${amount:.2f}"


def _pct(value: Any) -> str:
    return "자료 없음" if value is None else f"{float(value):.2f}%"
