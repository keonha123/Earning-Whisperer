from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from assistant.llm import LLMError, Message, StreamDone, TextDelta, Usage
from assistant.openai_client import OpenAIClient

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


class Answer(BaseModel):
    value: str


def _raw_usage(i=100, o=20, c=40):
    return SimpleNamespace(input_tokens=i, output_tokens=o, input_tokens_details=SimpleNamespace(cached_tokens=c))


class FakeStream:
    def __init__(self, events, final):
        self.events = events
        self.final = final
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event

    async def get_final_response(self):
        return self.final


class FakeResponses:
    def __init__(self, *, parse_result=None, parse_error=None, stream=None, stream_error=None):
        self.parse_result = parse_result
        self.parse_error = parse_error
        self._stream = stream
        self.stream_error = stream_error
        self.parse_kwargs = None
        self.stream_kwargs = None

    async def parse(self, **kwargs):
        self.parse_kwargs = kwargs
        if self.parse_error is not None:
            raise self.parse_error
        return self.parse_result

    def stream(self, **kwargs):
        self.stream_kwargs = kwargs
        if self.stream_error is not None:
            raise self.stream_error
        return self._stream


def _client(responses):
    return OpenAIClient(model="gpt-6-luna", parse_effort="none", stream_effort="none",
                        client=SimpleNamespace(responses=responses))


_MESSAGES = [Message("system", "규칙"), Message("user", "질문")]


async def test_parse_sends_model_effort_and_schema_and_maps_usage():
    responses = FakeResponses(parse_result=SimpleNamespace(output_parsed=Answer(value="ok"), usage=_raw_usage()))
    parsed, usage = await _client(responses).parse(_MESSAGES, Answer)

    assert parsed == Answer(value="ok")
    assert usage == Usage(100, 20, 40)
    kwargs = responses.parse_kwargs
    assert kwargs["model"] == "gpt-6-luna"
    assert kwargs["reasoning"] == {"effort": "none"}
    assert kwargs["store"] is False
    assert kwargs["text_format"] is Answer
    assert kwargs["input"] == [{"role": "system", "content": "규칙"}, {"role": "user", "content": "질문"}]


async def test_parse_without_parsed_output_is_unparsable():
    responses = FakeResponses(parse_result=SimpleNamespace(output_parsed=None, usage=_raw_usage()))
    with pytest.raises(LLMError) as error:
        await _client(responses).parse(_MESSAGES, Answer)
    assert error.value.code == "llm_unparsable"


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (openai.APITimeoutError(request=_REQUEST), "llm_timeout"),
        (openai.APIConnectionError(request=_REQUEST), "llm_failed"),
    ],
)
async def test_parse_maps_sdk_errors(exc, code):
    with pytest.raises(LLMError) as error:
        await _client(FakeResponses(parse_error=exc)).parse(_MESSAGES, Answer)
    assert error.value.code == code


async def test_stream_yields_text_deltas_then_usage():
    events = [
        SimpleNamespace(type="response.created"),
        SimpleNamespace(type="response.output_text.delta", delta="매출이 "),
        SimpleNamespace(type="response.output_text.delta", delta="늘었습니다 [S3]"),
        SimpleNamespace(type="response.completed"),
    ]
    stream = FakeStream(events, SimpleNamespace(usage=_raw_usage(1000, 50, 800)))
    responses = FakeResponses(stream=stream)

    items = [item async for item in _client(responses).stream(_MESSAGES)]

    assert items == [TextDelta("매출이 "), TextDelta("늘었습니다 [S3]"), StreamDone(Usage(1000, 50, 800))]
    assert responses.stream_kwargs["reasoning"] == {"effort": "none"}
    assert responses.stream_kwargs["store"] is False
    assert "text_format" not in responses.stream_kwargs
    assert stream.closed


async def test_stream_maps_errors_raised_mid_stream():
    stream = FakeStream(
        [SimpleNamespace(type="response.output_text.delta", delta="일부"), httpx.ReadTimeout("slow")],
        SimpleNamespace(usage=None),
    )
    received = []
    with pytest.raises(LLMError) as error:
        async for item in _client(FakeResponses(stream=stream)).stream(_MESSAGES):
            received.append(item)
    assert received == [TextDelta("일부")]
    assert error.value.code == "llm_timeout"


async def test_stream_maps_errors_on_open():
    responses = FakeResponses(stream_error=openai.APIConnectionError(request=_REQUEST))
    with pytest.raises(LLMError) as error:
        [item async for item in _client(responses).stream(_MESSAGES)]
    assert error.value.code == "llm_failed"


async def test_missing_usage_maps_to_zero():
    stream = FakeStream([], SimpleNamespace(usage=None))
    items = [item async for item in _client(FakeResponses(stream=stream)).stream(_MESSAGES)]
    assert items == [StreamDone(Usage())]


async def test_stream_maps_missing_completed_event():
    class StreamWithoutCompletedEvent(FakeStream):
        async def get_final_response(self):
            raise RuntimeError("Didn't receive a `response.completed` event.")

    events = [SimpleNamespace(type="response.output_text.delta", delta="데이터")]
    stream = StreamWithoutCompletedEvent(events, SimpleNamespace(usage=None))
    received = []
    with pytest.raises(LLMError) as error:
        async for item in _client(FakeResponses(stream=stream)).stream(_MESSAGES):
            received.append(item)
    assert received == [TextDelta("데이터")]
    assert error.value.code == "llm_failed"


def test_usage_add_and_as_dict():
    total = Usage(1, 2, 3)
    total.add(Usage(10, 20, 30))
    assert total.as_dict() == {"input_tokens": 11, "output_tokens": 22, "cached_tokens": 33}
