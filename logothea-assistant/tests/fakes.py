"""테스트 전용 가짜 의존성. 실제 OpenAI·backend·ai-engine 을 부르지 않는다."""

from __future__ import annotations

import asyncio

from assistant.clients import SourceUnavailable
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


NOT_FOUND = object()


def segments_payload(sequences, *, call_id="c1", base_epoch=1787227200):
    return {
        "call_id": call_id,
        "until_sequence": max(sequences) if sequences else 0,
        "last_sequence": max(sequences) if sequences else 0,
        "segments": [
            {"sequence": seq, "start_ms": seq * 6000, "end_ms": seq * 6000 + 5000, "speaker": "John Furner",
             "text": f"segment {seq} text", "timestamp": base_epoch + seq * 6}
            for seq in sequences
        ],
    }


class _FakeSource:
    def __init__(self, *, delays=None, fail=()):
        self.delays = delays or {}
        self.fail = set(fail)
        self.calls: list[tuple[str, dict]] = []

    async def _respond(self, name, kwargs, value):
        self.calls.append((name, kwargs))
        if name in self.delays:
            await asyncio.sleep(self.delays[name])
        if name in self.fail:
            raise SourceUnavailable(name, "fake")
        return value


class FakeBackend(_FakeSource):
    def __init__(self, *, segments=None, estimates=None, glossary=None, **kwargs):
        super().__init__(**kwargs)
        self.segments_value = segments if segments is not None else segments_payload([1, 2, 3])
        self.estimates_value = estimates
        self.glossary_value = glossary if glossary is not None else {"version": 1, "terms": []}

    async def segments(self, **kwargs):
        value = None if self.segments_value is NOT_FOUND else self.segments_value
        return await self._respond("segments", kwargs, value)

    async def estimates(self, **kwargs):
        return await self._respond("estimates", kwargs, self.estimates_value)

    async def glossary(self):
        return await self._respond("glossary", {}, self.glossary_value)


class FakeEngine(_FakeSource):
    def __init__(self, *, news=None, prior=None, **kwargs):
        super().__init__(**kwargs)
        self.news_value = news if news is not None else {"hits": [], "warnings": []}
        self.prior_value = prior if prior is not None else {"available": False, "statements": [],
                                                            "warnings": ["prior_call_not_found"]}

    async def news_search(self, **kwargs):
        return await self._respond("news_search", kwargs, self.news_value)

    async def prior_call_statements(self, **kwargs):
        return await self._respond("prior_call_statements", kwargs, self.prior_value)
