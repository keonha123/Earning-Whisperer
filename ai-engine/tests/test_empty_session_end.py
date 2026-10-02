from fastapi.testclient import TestClient
from main import create_app


def test_empty_legacy_end_is_control_only():
    client = TestClient(create_app())
    payload = dict(ticker="SMOKE", text_chunk="", sequence=3, timestamp=1700000000, is_final=True)
    result = client.post("/api/v1/analyze", json=payload)
    assert result.status_code == 200
    assert result.json()["is_session_end"] is True
    assert result.json()["execution_allowed"] is False
    assert result.json()["redis_published"] is False
    assert client.post("/api/v1/analyze", json={**payload, "is_final": False}).status_code == 422


def test_empty_factcheck_end_clears_only_its_call_without_llm():
    client = TestClient(create_app())
    payload = dict(ticker="SMOKE", call_id="a", sentence="Revenue increased.", sentence_sequence=0, sentence_timestamp=1700000000)
    route = "/v1/engine/live-fact-check/sentence"
    assert client.post(route, json=payload).json()["buffered_count"] == 1
    assert client.post(route, json={**payload, "call_id": "b"}).json()["buffered_count"] == 1
    ended = client.post(route, json={**payload, "sentence": "", "sentence_sequence": 1, "is_session_end": True})
    assert ended.status_code == 200
    assert ended.json()["extraction_llm_used"] is False
    assert ended.json()["warnings"] == ["partial_batch_discarded"]
    other = client.post(route, json={**payload, "call_id": "b", "sentence_sequence": 1})
    assert other.json()["buffered_count"] == 2
    assert client.post(route, json={**payload, "sentence": ""}).status_code == 422
