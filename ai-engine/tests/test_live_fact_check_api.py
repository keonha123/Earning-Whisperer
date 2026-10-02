"""라우터 계층 테스트 — /v1/engine/live-fact-check/sentence.

서비스 내부 동작은 test_live_news_fact_check_service.py 가 담당한다.
여기서는 "엔드포인트가 등록되었고, 요청/응답이 계약대로 직렬화되며,
버퍼 상태가 요청 간에 유지되는가" 만 본다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from core.external_retriever import ExternalRetrievedDocument


class _FakeRetriever:
    """3문장 배치의 각 주장에 대해 동일한 근거 묶음을 돌려준다."""

    def __init__(self, docs: list[ExternalRetrievedDocument]) -> None:
        self.docs = docs

    def retrieve_many(self, *, queries, **_kwargs):
        return [list(self.docs) for _ in queries]


class _FakeLlm:
    def __init__(self, *payloads) -> None:
        self.payloads = list(payloads)

    async def generate_content_with_metadata(self, **_kwargs):
        payload = self.payloads.pop(0)
        return SimpleNamespace(text=json.dumps(payload))


def _document(doc_id: str, publisher: str) -> ExternalRetrievedDocument:
    # 근거 게이트(_gate_evidence)는 강한 관련성 또는 서로 다른 매체 2곳을 요구한다.
    return ExternalRetrievedDocument(
        doc_id=doc_id,
        text="Oracle OCI revenue grew 42 percent year over year.",
        score=0.9,
        semantic_score=0.9,
        title=f"News {doc_id}",
        published_at=1_900_000_000,
        url=f"https://{publisher.lower()}.example.com/{doc_id}",
        metadata={"source": publisher},
    )


def _payload(sequence: int, sentence: str, *, ticker: str = "ORCL", end: bool = False) -> dict:
    return {
        "ticker": ticker,
        "sentence": sentence,
        "sentence_sequence": sequence,
        "sentence_timestamp": 1_900_000_000 + sequence,
        "is_session_end": end,
    }


def _client_with_stubs(llm: _FakeLlm | None = None) -> TestClient:
    app = main.create_app()
    service = app.state.live_news_fact_check_service
    service.retriever = _FakeRetriever([_document("d1", "Reuters"), _document("d2", "Bloomberg")])
    if llm is not None:
        service.llm_client = llm
    return TestClient(app)


def test_endpoint_is_published_in_openapi_schema() -> None:
    # 백엔드가 계약을 이 스키마에서 읽으므로 경로가 실제로 공개되는지까지 확인한다.
    schema = main.create_app().openapi()
    assert "/v1/engine/live-fact-check/sentence" in schema["paths"]


def test_first_two_sentences_buffer_without_calling_llm() -> None:
    # LLM 페이로드를 하나도 주지 않았으므로, 호출이 일어나면 IndexError 로 터진다.
    client = _client_with_stubs(_FakeLlm())

    first = client.post("/v1/engine/live-fact-check/sentence", json=_payload(0, "OCI revenue grew sharply."))
    assert first.status_code == 200
    assert first.json()["status"] == "BUFFERING"
    assert first.json()["buffered_count"] == 1

    second = client.post("/v1/engine/live-fact-check/sentence", json=_payload(1, "Gross margin narrowed."))
    assert second.json()["status"] == "BUFFERING"
    assert second.json()["buffered_count"] == 2


def test_third_sentence_completes_batch_with_verdicts() -> None:
    extraction = {
        "claims": [
            {
                "sentence_index": 0,
                "source_text": "OCI revenue grew 52 percent year over year.",
                "normalized_claim": "OCI revenue grew 52% year over year",
                "claim_type": "numeric_fact",
            }
        ],
        "excluded_count": 2,
    }
    verification = {
        "results": [
            {
                "claim_id": "ORCL:0-2:c1",
                "verdict": "CONTRADICTED",
                "confidence": 0.88,
                "explanation_ko": "보도자료는 42% 성장을 명시하고 있어 52% 주장과 배치됩니다.",
                "evidence_indices": [1],
            }
        ]
    }
    client = _client_with_stubs(_FakeLlm(extraction, verification))

    client.post("/v1/engine/live-fact-check/sentence", json=_payload(0, "OCI revenue grew 52 percent year over year."))
    client.post("/v1/engine/live-fact-check/sentence", json=_payload(1, "Gross margin narrowed slightly."))
    third = client.post("/v1/engine/live-fact-check/sentence", json=_payload(2, "We remain confident in demand."))

    assert third.status_code == 200
    body = third.json()
    assert body["status"] == "COMPLETED"
    assert body["ticker"] == "ORCL"
    assert body["batch_start_sequence"] == 0
    assert body["batch_end_sequence"] == 2
    assert body["extraction_llm_used"] is True
    assert len(body["claims"]) == 1
    claim = body["claims"][0]
    assert claim["verdict"] in {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}
    assert claim["explanation_ko"]
    assert "reason_code" in claim


def test_regressed_sequence_is_rejected_with_http_200() -> None:
    # REJECTED 는 HTTP 에러가 아니라 본문 status 로 전달된다 — 호출자가 분기해야 한다.
    client = _client_with_stubs(_FakeLlm())

    client.post("/v1/engine/live-fact-check/sentence", json=_payload(5, "First sentence."))
    duplicate = client.post("/v1/engine/live-fact-check/sentence", json=_payload(5, "Same sequence again."))

    assert duplicate.status_code == 200
    body = duplicate.json()
    assert body["status"] == "REJECTED"
    assert "duplicate_or_regressed_sequence" in body["warnings"]


def test_session_end_before_three_sentences_discards_partial_batch() -> None:
    client = _client_with_stubs(_FakeLlm())

    client.post("/v1/engine/live-fact-check/sentence", json=_payload(0, "Only sentence."))
    ended = client.post("/v1/engine/live-fact-check/sentence", json=_payload(1, "Call ends here.", end=True))

    assert ended.json()["status"] == "DISCARDED"
    assert "partial_batch_discarded" in ended.json()["warnings"]


def test_validation_error_returns_422() -> None:
    client = _client_with_stubs(_FakeLlm())
    response = client.post(
        "/v1/engine/live-fact-check/sentence",
        json={"ticker": "ORCL", "sentence": "", "sentence_sequence": -1, "sentence_timestamp": 0},
    )
    assert response.status_code == 422
