"""OpenAI Responses API 어댑터. 추론 강도는 호출 종류(분류·생성)별로 고정한다."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai
from pydantic import ValidationError

from assistant.llm import LLMError, Message, RoundDone, StreamDone, T, TextDelta, ToolCall, ToolResult, ToolSpec, Usage


class OpenAIClient:
    def __init__(
        self,
        *,
        model: str,
        parse_effort: str,
        stream_effort: str,
        client: Any | None = None,
        api_key: str = "",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client if client is not None else openai.AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._parse_effort = parse_effort
        self._stream_effort = stream_effort

    async def parse(self, messages: list[Message], schema: type[T]) -> tuple[T, Usage]:
        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=_to_input(messages),
                text_format=schema,
                reasoning={"effort": self._parse_effort},
                store=False,
            )
        except ValidationError as exc:
            raise LLMError("llm_unparsable", str(exc)) from exc
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise LLMError("llm_timeout", str(exc)) from exc
        except (openai.APIError, httpx.HTTPError) as exc:
            raise LLMError("llm_failed", str(exc)) from exc
        parsed = response.output_parsed
        if parsed is None:
            raise LLMError("llm_unparsable", "구조화 출력이 비어 있습니다")
        return parsed, _usage(response.usage)

    async def stream(self, messages: list[Message]) -> AsyncIterator[TextDelta | StreamDone]:
        try:
            async with self._client.responses.stream(
                model=self._model,
                input=_to_input(messages),
                reasoning={"effort": self._stream_effort},
                store=False,
            ) as stream:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        yield TextDelta(event.delta)
                try:
                    final = await stream.get_final_response()
                except RuntimeError as exc:
                    raise LLMError("llm_failed", str(exc)) from exc
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise LLMError("llm_timeout", str(exc)) from exc
        except (openai.APIError, httpx.HTTPError) as exc:
            raise LLMError("llm_failed", str(exc)) from exc
        yield StreamDone(_usage(final.usage))

    async def agent_round(self, items: list[Any], tools: list[ToolSpec], *,
                          allow_tools: bool) -> AsyncIterator[TextDelta | RoundDone]:
        try:
            async with self._client.responses.stream(
                model=self._model,
                input=[_to_agent_input(item) for item in items],
                tools=[_tool(spec) for spec in tools],
                tool_choice="auto" if allow_tools else "none",
                reasoning={"effort": self._stream_effort},
                store=False,
                # store=False 라 추론 항목을 다음 라운드에 넘기려면 암호화된 원문이 필요하다.
                include=["reasoning.encrypted_content"],
            ) as stream:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        yield TextDelta(event.delta)
                try:
                    final = await stream.get_final_response()
                except RuntimeError as exc:
                    raise LLMError("llm_failed", str(exc)) from exc
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise LLMError("llm_timeout", str(exc)) from exc
        except (openai.APIError, httpx.HTTPError) as exc:
            raise LLMError("llm_failed", str(exc)) from exc
        calls = [ToolCall(call_id=item.call_id, name=item.name, arguments=item.arguments)
                 for item in final.output if item.type == "function_call"]
        yield RoundDone(usage=_usage(final.usage), tool_calls=calls, items=[_replay(item) for item in final.output])


def _to_input(messages: list[Message]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.text} for message in messages]


def _to_agent_input(item: Any) -> Any:
    if isinstance(item, Message):
        return {"role": item.role, "content": item.text}
    if isinstance(item, ToolResult):
        return {"type": "function_call_output", "call_id": item.call_id, "output": item.output}
    return item


def _tool(spec: ToolSpec) -> dict[str, Any]:
    return {"type": "function", "name": spec.name, "description": spec.description,
            "parameters": spec.parameters, "strict": True}


def _replay(item: Any) -> dict[str, Any]:
    """출력 항목을 다음 라운드 입력 형태로 바꾼다. store=False 라 id 로 참조할 수 없어 내용째 넘긴다."""
    if item.type == "function_call":
        return {"type": "function_call", "call_id": item.call_id, "name": item.name, "arguments": item.arguments}
    if item.type == "message":
        text = "".join(part.text for part in item.content if getattr(part, "type", "") == "output_text")
        return {"role": "assistant", "content": text}
    return item.model_dump(exclude_none=True)


def _usage(raw: Any) -> Usage:
    if raw is None:
        return Usage()
    details = getattr(raw, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details is not None else 0
    return Usage(
        input_tokens=raw.input_tokens or 0,
        output_tokens=raw.output_tokens or 0,
        cached_tokens=cached or 0,
    )
