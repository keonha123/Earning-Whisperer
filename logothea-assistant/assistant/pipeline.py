"""1단계 고정 RAG 파이프라인: 분류 → 근거 수집 → 생성(스트리밍) → 인용 검증.

분류를 기다리는 동안 세그먼트·실적 추정치·직전 콜 조회를 먼저 시작해 첫 토큰까지의 지연을 줄인다.
뉴스는 분류가 만든 검색어가 필요해 분류 뒤에 찾는다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Any

from assistant.citations import verify_citations
from assistant.classifier import Classification, GlossaryProvider, classify, glossary_answer
from assistant.context import ContextAssembler, ContextError
from assistant.llm import LLMClient, LLMError, StreamDone, TextDelta, Usage
from assistant.prompts import NO_EVIDENCE_PHRASE, REFUSAL_SUGGESTIONS, REFUSAL_TEXTS, build_generation_messages
from assistant.schemas import AskRequest

logger = logging.getLogger(__name__)

Event = tuple[str, Any]

ERROR_MESSAGES: dict[str, str] = {
    "llm_timeout": "답변 생성이 제한 시간을 넘었습니다. 잠시 후 다시 질문해 주세요.",
    "llm_failed": "답변을 만들지 못했습니다. 잠시 후 다시 질문해 주세요.",
    "llm_unparsable": "질문을 해석하지 못했습니다. 다시 질문해 주세요.",
    "segments_not_found": "이 콜의 자막을 찾지 못했습니다.",
    "context_unavailable": "콜 자막을 불러오지 못했습니다. 잠시 후 다시 질문해 주세요.",
    "internal": "알 수 없는 오류가 발생했습니다.",
}


def error_event(code: str) -> Event:
    return "error", {"code": code, "message": ERROR_MESSAGES.get(code, ERROR_MESSAGES["internal"])}


class AnswerPipeline:
    def __init__(self, *, llm: LLMClient, assembler: ContextAssembler, glossary: GlossaryProvider,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._llm = llm
        self._assembler = assembler
        self._glossary = glossary
        self._clock = clock

    async def run(self, request: AskRequest) -> AsyncIterator[Event]:
        started = self._clock()
        usage = Usage()
        base_task = asyncio.create_task(self._assembler.gather_base(request))
        try:
            try:
                classification, classify_usage = await classify(self._llm, request)
            except LLMError as exc:
                yield error_event(exc.code)
                return
            usage.add(classify_usage)
            category = classification.category

            if category in REFUSAL_TEXTS:
                yield "meta", _meta(request, request.as_of_sequence, request.anchor_sequence, [])
                yield "delta", {"text": REFUSAL_TEXTS[category]}
                yield self._done(started, usage, category, status="refused", refusal_reason=category,
                                 suggested=REFUSAL_SUGGESTIONS[category])
                return

            if category == "glossary":
                entry = await self._glossary_entry(classification)
                if entry is not None:
                    yield "meta", _meta(request, request.as_of_sequence, request.anchor_sequence, [])
                    yield "delta", {"text": glossary_answer(entry)}
                    yield self._done(started, usage, category, status="answered")
                    return
                category = "answer"

            try:
                base = await base_task
                news_hits, news_missing = await self._assembler.gather_news(request, classification.search_query)
                bundle = self._assembler.build(request, base, news_hits, news_missing)
            except ContextError as exc:
                yield error_event(exc.code)
                return

            yield "meta", _meta(request, bundle.as_of_sequence, bundle.anchor_sequence, bundle.missing_sources)
            parts: list[str] = []
            try:
                # 소비하는 쪽이 끊으면 aclosing 이 LLM 스트림을 닫아 공급자 연결과 과금을 멈춘다.
                async with aclosing(self._llm.stream(build_generation_messages(request, bundle, category))) as stream:
                    async for item in stream:
                        if isinstance(item, TextDelta):
                            parts.append(item.text)
                            yield "delta", {"text": item.text}
                        elif isinstance(item, StreamDone):
                            usage.add(item.usage)
            except LLMError as exc:
                yield error_event(exc.code)
                return

            answer = "".join(parts)
            result = verify_citations(answer, bundle.evidence)
            yield "citations", result.citations
            status = "no_evidence" if NO_EVIDENCE_PHRASE in answer and not result.citations else "answered"
            yield self._done(started, usage, category, status=status, warnings=result.warnings)
        finally:
            _discard(base_task)

    async def _glossary_entry(self, classification: Classification) -> dict[str, Any] | None:
        glossary = await self._glossary.get()
        return glossary.lookup(classification.glossary_term) if glossary is not None else None

    def _done(self, started: float, usage: Usage, category: str, *, status: str, refusal_reason: str | None = None,
              suggested: list[str] | tuple[str, ...] = (), warnings: list[str] | tuple[str, ...] = ()) -> Event:
        latency_ms = int((self._clock() - started) * 1000)
        logger.info("질의응답 완료 category=%s status=%s input=%d output=%d cached=%d latency_ms=%d warnings=%s",
                    category, status, usage.input_tokens, usage.output_tokens, usage.cached_tokens, latency_ms,
                    list(warnings))
        return "done", {"status": status, "refusal_reason": refusal_reason, "suggested_question_ids": list(suggested),
                        "warnings": list(warnings), "usage": usage.as_dict(), "latency_ms": latency_ms}


def _meta(request: AskRequest, as_of_sequence: int, anchor: int | None, missing: list[str]) -> dict[str, Any]:
    as_of_time = datetime.fromtimestamp(request.as_of_epoch, UTC).isoformat().replace("+00:00", "Z")
    return {"scope": "anchor" if anchor is not None else "call", "as_of_sequence": as_of_sequence,
            "as_of_time": as_of_time, "anchor_sequence": anchor, "missing_sources": list(missing)}


def _discard(task: asyncio.Task[Any]) -> None:
    if not task.done():
        task.cancel()
    elif not task.cancelled():
        # 거절 경로처럼 결과를 쓰지 않은 실패를 회수해 "exception was never retrieved" 경고를 막는다.
        task.exception()
