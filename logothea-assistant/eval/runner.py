"""assistant 를 직접 불러 한 문항의 SSE 를 모은다.

backend 외부 엔드포인트(JWT·하루 한도)를 거치지 않고 assistant 내부 엔드포인트를 부른다. backend 가 하던 as_of 확정은
고정 세그먼트로 여기서 한다(as_of_epoch = 그 세그먼트 시각, call_ended = 그 세그먼트가 마지막인지).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from eval.dataset import EvalItem
from eval.transcript import EvalSegment


@dataclass
class ItemResult:
    item_id: str
    status: str | None = None
    refusal_reason: str | None = None
    answer: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    error: dict[str, str] | None = None
    first_token_ms: int | None = None
    total_ms: int = 0
    server_latency_ms: int | None = None


class AssistantRunner:
    def __init__(self, http: httpx.Client, *, assistant_url: str, secret: str, ticker: str, call_id: str,
                 segments: list[EvalSegment], clock: Callable[[], float] = time.perf_counter) -> None:
        self._http = http
        self._url = assistant_url.rstrip("/") + "/v1/assistant/ask"
        self._secret = secret
        self._ticker = ticker
        self._call_id = call_id
        self._segments = segments
        self._clock = clock

    def run_item(self, item: EvalItem) -> ItemResult:
        as_of = self._segments[item.as_of_sequence]
        payload = {
            "user_id": "eval", "ticker": self._ticker, "call_id": self._call_id,
            "as_of_sequence": item.as_of_sequence, "as_of_epoch": as_of.timestamp,
            "anchor_sequence": item.anchor_sequence, "call_ended": as_of.is_session_end,
            "question": item.question, "suggested_question_id": item.suggested_question_id,
            "history": [turn.model_dump() for turn in item.history],
        }
        result = ItemResult(item_id=item.id)
        started = self._clock()
        try:
            with self._http.stream("POST", self._url, json=payload, headers={"X-Internal-Secret": self._secret},
                                   timeout=90.0) as response:
                if response.status_code != 200:
                    body = response.read().decode("utf-8", errors="ignore")[:500]
                    result.error = {"code": f"http_{response.status_code}", "message": body}
                else:
                    self._collect(response, result, started)
        except httpx.HTTPError as exc:
            result.error = {"code": "connect_failed", "message": type(exc).__name__}
        except Exception as exc:  # 한 문항의 예기치 못한 실패가 실행 전체를 멈추지 않게 한다
            result.error = {"code": "runner_exception", "message": type(exc).__name__}
        result.total_ms = int((self._clock() - started) * 1000)
        return result

    def _collect(self, response: httpx.Response, result: ItemResult, started: float) -> None:
        event: str | None = None
        data_lines: list[str] = []
        for line in _sse_lines(response):
            if line == "":
                if event is not None and data_lines:
                    try:
                        self._apply(event, json.loads("\n".join(data_lines)), result, started)
                    except (ValueError, AttributeError, TypeError, KeyError) as exc:
                        result.error = {"code": "bad_frame", "message": type(exc).__name__}
                        return
                event, data_lines = None, []
            elif line.startswith(":"):
                continue
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if result.status is None and result.error is None:
            result.error = {"code": "incomplete_stream", "message": ""}

    def _apply(self, event: str, data: Any, result: ItemResult, started: float) -> None:
        if event == "meta":
            result.meta = data
        elif event == "delta":
            if result.first_token_ms is None:
                result.first_token_ms = int((self._clock() - started) * 1000)
            result.answer += data.get("text", "")
        elif event == "citations":
            result.citations = list(data)
        elif event == "done":
            result.status = data.get("status")
            result.refusal_reason = data.get("refusal_reason")
            result.warnings = list(data.get("warnings") or [])
            result.usage = dict(data.get("usage") or {})
            result.server_latency_ms = data.get("latency_ms")
        elif event == "error":
            result.error = {"code": data.get("code", "internal"), "message": data.get("message", "")}


def _sse_lines(response: httpx.Response):
    """SSE 줄을 '\n' 으로만 나눈다. httpx.iter_lines 는 U+2028 같은 유니코드 줄 구분 문자에서도 끊어,
    답 본문에 그 문자가 섞이면 JSON 이 잘린다."""
    buffer = ""
    for chunk in response.iter_text():
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield line[:-1] if line.endswith("\r") else line
    if buffer:
        yield buffer
