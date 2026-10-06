"""테스트 전용 가짜 의존성. 실제 OpenAI·backend·ai-engine 을 부르지 않는다."""

from __future__ import annotations

from assistant.llm import Message, StreamDone, TextDelta, Usage


class FakeLLM:
    def __init__(
        self,
        *,
        parsed=None,
        deltas=(),
        parse_usage: Usage | None = None,
        stream_usage: Usage | None = None,
        parse_error: Exception | None = None,
        stream_error: Exception | None = None,
        fail_after: int = 0,
    ) -> None:
        self.parsed = parsed
        self.deltas = list(deltas)
        self.parse_usage = parse_usage or Usage(30, 10, 0)
        self.stream_usage = stream_usage or Usage(1000, 50, 800)
        self.parse_error = parse_error
        self.stream_error = stream_error
        self.fail_after = fail_after
        self.parse_calls: list[list[Message]] = []
        self.stream_calls: list[list[Message]] = []
        self.stream_closed = False

    async def parse(self, messages, schema):
        self.parse_calls.append(messages)
        if self.parse_error is not None:
            raise self.parse_error
        return self.parsed, self.parse_usage

    async def stream(self, messages):
        self.stream_calls.append(messages)
        try:
            for index, text in enumerate(self.deltas):
                if self.stream_error is not None and index == self.fail_after:
                    raise self.stream_error
                yield TextDelta(text)
            if self.stream_error is not None:
                raise self.stream_error
            yield StreamDone(self.stream_usage)
        finally:
            self.stream_closed = True
