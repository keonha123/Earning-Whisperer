import json

from fastapi.testclient import TestClient

from assistant.app import create_app, format_sse
from assistant.config import Settings

_BODY = {"user_id": "u1", "ticker": "WMT", "call_id": "c1", "as_of_sequence": 3, "as_of_epoch": 1787227218,
         "question": "요약해 줘"}


class StubPipeline:
    def __init__(self, events=(), error=None):
        self.events = list(events)
        self.error = error
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


def _client(pipeline, secret="s3cret"):
    settings = Settings(_env_file=None, internal_secret=secret, openai_api_key="")
    return TestClient(create_app(settings=settings, pipeline=pipeline))


def _parse(text):
    events = []
    for block in text.strip().split("\n\n"):
        name_line, data_line = block.split("\n")
        events.append((name_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
    return events


def test_format_sse_keeps_korean_readable():
    assert format_sse("delta", {"text": "매출"}) == 'event: delta\ndata: {"text": "매출"}\n\n'


def test_rejects_missing_or_wrong_secret():
    pipeline = StubPipeline()
    client = _client(pipeline)
    assert client.post("/v1/assistant/ask", json=_BODY).status_code == 401
    assert client.post("/v1/assistant/ask", json=_BODY, headers={"X-Internal-Secret": "nope"}).status_code == 401
    assert pipeline.requests == []


def test_rejects_everything_when_secret_is_not_configured():
    client = _client(StubPipeline(), secret="")
    assert client.post("/v1/assistant/ask", json=_BODY, headers={"X-Internal-Secret": ""}).status_code == 401


def test_secret_is_checked_before_body_validation():
    client = _client(StubPipeline())
    assert client.post("/v1/assistant/ask", json={"question": ""}).status_code == 401


def test_invalid_body_is_422():
    client = _client(StubPipeline())
    response = client.post("/v1/assistant/ask", json={**_BODY, "question": "가" * 501},
                           headers={"X-Internal-Secret": "s3cret"})
    assert response.status_code == 422


def test_streams_pipeline_events_as_sse():
    pipeline = StubPipeline(events=[("meta", {"scope": "call"}), ("delta", {"text": "요약"}), ("done", {"status": "answered"})])
    response = _client(pipeline).post("/v1/assistant/ask", json=_BODY, headers={"X-Internal-Secret": "s3cret"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert _parse(response.text) == [("meta", {"scope": "call"}), ("delta", {"text": "요약"}), ("done", {"status": "answered"})]
    assert pipeline.requests[0].question == "요약해 줘"


def test_unexpected_pipeline_failure_ends_with_internal_error_event():
    pipeline = StubPipeline(events=[("meta", {"scope": "call"})], error=RuntimeError("boom"))
    response = _client(pipeline).post("/v1/assistant/ask", json=_BODY, headers={"X-Internal-Secret": "s3cret"})
    events = _parse(response.text)
    assert events[-1] == ("error", {"code": "internal", "message": "알 수 없는 오류가 발생했습니다."})


def test_health():
    assert _client(StubPipeline()).get("/health").json() == {"status": "ok"}
