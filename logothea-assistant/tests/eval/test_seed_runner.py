import json

import httpx
import pytest

from eval.dataset import EvalItem, EvalTurn
from eval.runner import AssistantRunner
from eval.seed import SeedError, new_call_id, seed_segments
from eval.transcript import EvalSegment

SEGMENTS = [EvalSegment(i, i * 5000, i * 5000 + 4500, "CEO · A", f"t{i}", 1787227200 + i * 5, i == 2) for i in range(3)]


def test_new_call_id_is_unique_per_run():
    assert new_call_id(now=lambda: 1787300000.5) == "eval-wmt-q2fy27-1787300000"


def test_seed_posts_every_segment_then_waits_for_storage():
    posted = []
    reads = iter([0, 2])

    def handler(request):
        if request.method == "POST":
            posted.append(json.loads(request.content))
            assert request.headers["X-Internal-Secret"] == "s"
            return httpx.Response(202, json={})
        return httpx.Response(200, json={"last_sequence": next(reads), "segments": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        count = seed_segments(http, backend_url="http://b", secret="s", ticker="WMT", call_id="c1",
                              segments=SEGMENTS, sleep=lambda _s: None)

    assert count == 3
    assert posted[0] == {"ticker": "WMT", "call_id": "c1", "sequence": 0, "start_ms": 0, "end_ms": 4500,
                         "text": "t0", "speaker": "CEO · A", "timestamp": 1787227200, "is_session_end": False}
    assert posted[2]["is_session_end"] is True


def test_seed_fails_on_rejection():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(409, json={}))) as http:
        with pytest.raises(SeedError):
            seed_segments(http, backend_url="http://b", secret="s", ticker="WMT", call_id="c1",
                          segments=SEGMENTS, sleep=lambda _s: None)


def _sse(*events):
    return "".join(f"event:{name}\ndata:{json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events)


def test_runner_sends_payload_and_collects_events():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["secret"] = request.headers["X-Internal-Secret"]
        body = _sse(
            ("meta", {"scope": "call", "as_of_sequence": 2}),
            ("delta", {"text": "매출 "}),
            ("delta", {"text": "증가 [S1]."}),
            ("citations", [{"marker": "S1", "type": "segment", "ref": "1", "verified": True}]),
            ("done", {"status": "answered", "refusal_reason": None, "warnings": [], "usage": {"input_tokens": 10, "output_tokens": 2, "cached_tokens": 0}, "latency_ms": 900}),
        ) + ":\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    ticks = iter([0.0, 0.25, 1.0])
    item = EvalItem(id="a1", group="follow_up", question="그건 왜야?", as_of_sequence=2, anchor_sequence=1,
                    expected_status="answered", key_points=["a", "b"], gold_sequences=[1],
                    history=[EvalTurn(role="user", text="앞")])
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        runner = AssistantRunner(http, assistant_url="http://a", secret="s", ticker="WMT", call_id="c1",
                                 segments=SEGMENTS, clock=lambda: next(ticks))
        result = runner.run_item(item)

    assert seen["secret"] == "s"
    assert seen["body"] == {"user_id": "eval", "ticker": "WMT", "call_id": "c1", "as_of_sequence": 2,
                            "as_of_epoch": 1787227210, "anchor_sequence": 1, "call_ended": True, "question": "그건 왜야?",
                            "suggested_question_id": None, "history": [{"role": "user", "text": "앞"}]}
    assert result.answer == "매출 증가 [S1]."
    assert result.status == "answered"
    assert result.citations[0]["marker"] == "S1"
    assert result.usage == {"input_tokens": 10, "output_tokens": 2, "cached_tokens": 0}
    assert result.first_token_ms == 250
    assert result.total_ms == 1000
    assert result.server_latency_ms == 900
    assert result.error is None


def test_runner_records_error_event_and_http_failure():
    def handler(request):
        return httpx.Response(200, text=_sse(("meta", {}), ("error", {"code": "llm_timeout", "message": "m"})))

    item = EvalItem(id="e1", group="answerable", question="q", as_of_sequence=1, expected_status="answered",
                    key_points=["a", "b"], gold_sequences=[0])
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = AssistantRunner(http, assistant_url="http://a", secret="s", ticker="WMT", call_id="c1", segments=SEGMENTS).run_item(item)
    assert result.status is None and result.error == {"code": "llm_timeout", "message": "m"}

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))) as http:
        result = AssistantRunner(http, assistant_url="http://a", secret="s", ticker="WMT", call_id="c1", segments=SEGMENTS).run_item(item)
    assert result.error == {"code": "http_401", "message": ""}

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    with httpx.Client(transport=httpx.MockTransport(boom)) as http:
        result = AssistantRunner(http, assistant_url="http://a", secret="s", ticker="WMT", call_id="c1", segments=SEGMENTS).run_item(item)
    assert result.error["code"] == "connect_failed"
