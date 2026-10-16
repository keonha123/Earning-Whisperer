"""도구 호출 에이전트 답변.

분류·거절·용어 경로는 pipeline 이 그대로 맡고, 여기서는 "근거 모으기 + 생성" 만 한다. 매 라운드를 스트림으로 받아
글 조각은 바로 내보내고, 도구 호출이 있으면 결과를 이어 붙여 다음 라운드를 돈다. 라운드 상한에 닿으면 도구 없이
답을 쓰게 한다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from assistant.context import (BaseSources, ContextAssembler, ContextError, Evidence, estimate_evidence,
                               meta_payload, prior_evidence, segment_scope)
from assistant.llm import LLMClient, LLMError, RoundDone, TextDelta, Usage
from assistant.prompts import build_agent_messages
from assistant.schemas import AskRequest
from assistant.tools import TOOL_SPECS, AgentToolbox

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4
# 대목 질문은 고른 대목과 앞뒤 두 발언을 처음부터 보여 준다.
ANCHOR_NEIGHBORS = 2


@dataclass
class AgentFinished:
    answer: str
    evidence: dict[str, Evidence]
    warnings: list[str] = field(default_factory=list)


class AgentAnswerer:
    def __init__(self, llm: LLMClient, assembler: ContextAssembler) -> None:
        self._llm = llm
        self._assembler = assembler

    async def run(self, request: AskRequest, base: BaseSources, category: str,
                  usage: Usage) -> AsyncIterator[tuple[str, dict[str, Any]] | AgentFinished]:
        segments, incomplete, anchor = segment_scope(base.segments, request)
        if not segments:
            raise ContextError("segments_not_found")
        missing = [*base.missing_sources, *incomplete]

        async def news_search(query: str) -> tuple[list[dict[str, Any]], list[str]]:
            return await self._assembler.gather_news(request, query)

        toolbox = AgentToolbox(segments=segments, prior=prior_evidence(base.prior),
                               estimates=estimate_evidence(base.estimates, request.as_of_epoch),
                               anchor_sequence=anchor, news_search=news_search, as_of_epoch=request.as_of_epoch)
        preload = ""
        if anchor is not None:
            neighbors = [item for item in segments if abs(int(item.ref) - anchor) <= ANCHOR_NEIGHBORS]
            preload = toolbox.preload(neighbors)
        items: list[Any] = build_agent_messages(request, preload=preload, first_marker=segments[0].marker,
                                                last_marker=segments[-1].marker, anchor_sequence=anchor,
                                                category=category, missing=missing)
        parts: list[str] = []
        warnings: list[str] = []
        meta_sent = False

        def meta() -> tuple[str, dict[str, Any]]:
            return "meta", meta_payload(request, int(segments[-1].ref), anchor, [*missing, *toolbox.missing_sources])

        for round_index in range(MAX_TOOL_ROUNDS + 1):
            allow_tools = round_index < MAX_TOOL_ROUNDS
            if not allow_tools:
                warnings.append("agent_round_limit")
            done: RoundDone | None = None
            async with aclosing(self._llm.agent_round(items, TOOL_SPECS, allow_tools=allow_tools)) as stream:
                async for item in stream:
                    if isinstance(item, TextDelta):
                        if not meta_sent:
                            meta_sent = True
                            yield meta()
                        parts.append(item.text)
                        yield "delta", {"text": item.text}
                    elif isinstance(item, RoundDone):
                        done = item
            if done is None:
                raise LLMError("llm_failed", "도구 라운드가 끝 표시 없이 끝났습니다")
            usage.add(done.usage)
            if not done.tool_calls or not allow_tools:
                break
            results = [await toolbox.call(call) for call in done.tool_calls]
            items = [*items, *done.items, *results]

        if not meta_sent:
            yield meta()
        logger.info("에이전트 도구 호출 rounds=%d tools=%s", round_index + 1, toolbox.call_names)
        yield AgentFinished(answer="".join(parts), evidence=toolbox.evidence, warnings=warnings)
