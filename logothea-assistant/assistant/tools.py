"""에이전트 도구 상자.

콜 세그먼트·직전 콜·추정치는 분류와 병렬로 미리 읽어 둔 것에서 꺼내 주고, 뉴스만 호출 때 검색한다. 도구 결과는
고정 방식과 같은 근거 표시(S·N·P·E)로 렌더링해 인용 검증과 화면을 그대로 쓴다. 잘못된 인자·없는 도구·한도 초과는
예외 대신 결과 문자열로 알려 모델이 다음 행동을 고르게 한다.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable
from typing import Any

from assistant.context import Evidence, news_evidence
from assistant.llm import ToolCall, ToolResult, ToolSpec
from assistant.prompts import render_items
from assistant.segment_search import SegmentIndex

MAX_TOOL_CALLS = 8
MAX_SEARCH_HITS = 8
MAX_READ_SEGMENTS = 40

NewsSearch = Callable[[str], Awaitable[tuple[list[dict[str, Any]], list[str]]]]


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TOOL_SPECS = [
    ToolSpec("search_call", "질문 시점까지의 콜 발언에서 키워드로 관련 대목을 찾는다. 콜 원문이 영어라 검색어는 영어로 쓴다.",
             _schema({"query": {"type": "string", "description": "영어 키워드 검색어"}})),
    ToolSpec("read_call", f"콜 발언을 번호 범위로 차례대로 읽는다. 한 번에 최대 {MAX_READ_SEGMENTS}개.",
             _schema({"start_sequence": {"type": "integer"}, "end_sequence": {"type": "integer"}})),
    ToolSpec("search_news", "질문 시점 이전에 발행된 이 종목 관련 뉴스를 찾는다. 검색어는 영어로 쓴다.",
             _schema({"query": {"type": "string", "description": "영어 뉴스 검색어"}})),
    ToolSpec("get_prior_call", "지난 분기 실적 발표 콜의 경영진 주요 발언을 읽는다.", _schema({})),
    ToolSpec("get_estimates", "이번·다음 실적 발표의 시장 예상(EPS·매출)과 최근 분기 실적·서프라이즈를 읽는다.", _schema({})),
]


class AgentToolbox:
    def __init__(self, *, segments: list[Evidence], prior: list[Evidence], estimates: list[Evidence],
                 anchor_sequence: int | None, news_search: NewsSearch, as_of_epoch: int) -> None:
        self._segments = segments
        self._by_sequence = {int(item.ref): item for item in segments}
        self._index = SegmentIndex(segments)
        self._prior = prior
        self._estimates = estimates
        self._anchor = anchor_sequence
        self._news_search = news_search
        self._as_of_epoch = as_of_epoch
        self._news_markers: dict[str, str] = {}
        self.evidence: dict[str, Evidence] = {}
        self.missing_sources: list[str] = []
        self.call_names: list[str] = []

    def preload(self, items: list[Evidence]) -> str:
        return self._render(items)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call_id=call.call_id, output=await self._dispatch(call))

    async def _dispatch(self, call: ToolCall) -> str:
        if len(self.call_names) >= MAX_TOOL_CALLS:
            return f"도구 호출 한도({MAX_TOOL_CALLS}회)를 넘었습니다. 지금까지 모은 자료로 답한다."
        self.call_names.append(call.name)
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            return "인자를 읽지 못했습니다. JSON 형식으로 다시 부른다."
        if call.name == "search_call":
            hits = self._index.search(str(args.get("query", "")), MAX_SEARCH_HITS)
            if not hits:
                return "콜 발언에서 찾지 못했습니다. 다른 영어 키워드로 찾거나 read_call 로 읽는다."
            return self._render(sorted(hits, key=lambda item: int(item.ref)))
        if call.name == "read_call":
            return self._read(args)
        if call.name == "search_news":
            return await self._news(str(args.get("query", "")))
        if call.name == "get_prior_call":
            return self._render(self._prior) if self._prior else "지난 분기 콜 자료가 없습니다."
        if call.name == "get_estimates":
            return self._render(self._estimates) if self._estimates else "실적 추정치 자료가 없습니다."
        return f"없는 도구입니다: {call.name}"

    def _read(self, args: dict[str, Any]) -> str:
        try:
            start, end = int(args["start_sequence"]), int(args["end_sequence"])
        except (KeyError, TypeError, ValueError):
            return "인자를 읽지 못했습니다. start_sequence 와 end_sequence 를 정수로 준다."
        rows = [self._by_sequence[seq] for seq in sorted(self._by_sequence) if start <= seq <= end]
        if not rows:
            return "그 범위에 콜 발언이 없습니다."
        text = self._render(rows[:MAX_READ_SEGMENTS])
        if len(rows) > MAX_READ_SEGMENTS:
            next_start = int(rows[MAX_READ_SEGMENTS].ref)
            text += f"\n이어서 읽으려면 start_sequence={next_start} 부터 부른다."
        return text

    async def _news(self, query: str) -> str:
        hits, missing = await self._news_search(query)
        for name in missing:
            if name not in self.missing_sources:
                self.missing_sources.append(name)
        items = []
        for item in news_evidence(hits, self._as_of_epoch):
            marker = self._news_markers.setdefault(item.ref, f"N{len(self._news_markers) + 1}")
            items.append(dataclasses.replace(item, marker=marker))
        if not items:
            return "관련 뉴스를 불러오지 못했습니다." if missing else "관련 뉴스를 찾지 못했습니다."
        return self._render(items)

    def _render(self, items: list[Evidence]) -> str:
        for item in items:
            self.evidence[item.marker] = item
        return render_items(items, self._anchor)
