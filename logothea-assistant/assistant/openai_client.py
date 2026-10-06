"""OpenAI Responses API 어댑터. 추론 강도는 호출 종류(분류·생성)별로 고정한다."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai
from pydantic import ValidationError

from assistant.llm import LLMError, Message, StreamDone, T, TextDelta, Usage


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
                final = await stream.get_final_response()
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise LLMError("llm_timeout", str(exc)) from exc
        except (openai.APIError, httpx.HTTPError) as exc:
            raise LLMError("llm_failed", str(exc)) from exc
        yield StreamDone(_usage(final.usage))


def _to_input(messages: list[Message]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.text} for message in messages]


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
