"""공급자와 무관한 얇은 LLM 인터페이스.

파이프라인은 이 모듈의 타입만 알고, 공급자별 호출 방식은 어댑터(openai_client.py)가 맡는다.
공급자를 바꾸거나 테스트에서 가짜 LLM 을 넣을 때 파이프라인 코드는 바뀌지 않는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    text: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_tokens += other.cached_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class StreamDone:
    usage: Usage


class LLMError(Exception):
    """공급자 호출 실패. code 는 SSE error 이벤트의 code 로 그대로 나간다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolSpec:
    """모델에 알려 줄 도구. parameters 는 strict 구조화 출력 규칙(모든 필드 required, additionalProperties false)을 따른다."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    output: str


@dataclass(frozen=True)
class RoundDone:
    """도구 라운드 한 번의 끝. items 는 다음 라운드 입력에 그대로 이어 붙이는 공급자 원형 기록이다."""

    usage: Usage
    tool_calls: list[ToolCall]
    items: list[Any]


class LLMClient(Protocol):
    async def parse(self, messages: list[Message], schema: type[T]) -> tuple[T, Usage]:
        """구조화 출력으로 한 번 호출하고 schema 인스턴스를 돌려준다."""
        ...

    def stream(self, messages: list[Message]) -> AsyncIterator[TextDelta | StreamDone]:
        """텍스트 조각을 차례로 내고, 마지막에 StreamDone 을 한 번 낸다."""
        ...

    def agent_round(self, items: list[Any], tools: list[ToolSpec], *,
                    allow_tools: bool) -> AsyncIterator[TextDelta | RoundDone]:
        """도구를 쓸 수 있는 생성 한 번. 글 조각을 차례로 내고, 마지막에 RoundDone 을 한 번 낸다."""
        ...
