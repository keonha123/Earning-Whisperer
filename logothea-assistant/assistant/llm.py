"""공급자와 무관한 얇은 LLM 인터페이스.

파이프라인은 이 모듈의 타입만 알고, 공급자별 호출 방식은 어댑터(openai_client.py)가 맡는다.
공급자를 바꾸거나 테스트에서 가짜 LLM 을 넣을 때 파이프라인 코드는 바뀌지 않는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

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


class LLMClient(Protocol):
    async def parse(self, messages: list[Message], schema: type[T]) -> tuple[T, Usage]:
        """구조화 출력으로 한 번 호출하고 schema 인스턴스를 돌려준다."""
        ...

    def stream(self, messages: list[Message]) -> AsyncIterator[TextDelta | StreamDone]:
        """텍스트 조각을 차례로 내고, 마지막에 StreamDone 을 한 번 낸다."""
        ...
