"""라우터 계층 테스트 — logothea-assistant 근거 조회 (#112).

검색기 · 저장소는 가짜로 바꿔 끼운다. 여기서는 시점 조건, 실패 시 응답 형태,
직전 콜 조회 분기만 본다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

import main
from core.external_retriever import ExternalRetrievedDocument
from models.transcript_statement_models import KeyStatement

AS_OF = 1_787_227_200  # 2026-08-20T12:00:00Z


def _doc(doc_id: str, published_at: int, *, source: str = "Reuters") -> ExternalRetrievedDocument:
    return ExternalRetrievedDocument(
        doc_id=doc_id,
        text="Walmart U.S. comparable sales rose 2.6%. " * 40,
        score=0.8,
        semantic_score=0.8,
        title=f"News {doc_id}",
        published_at=published_at,
        url=f"https://example.com/{doc_id}",
        metadata={"source": source},
    )


class _FakeRetriever:
    def __init__(self, docs=None, error: Exception | None = None) -> None:
        self.docs = docs or []
        self.error = error
        self.calls: list[dict] = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return list(self.docs)


class _FakeTranscriptRepository:
    def __init__(self, latest: dict | None) -> None:
        self.latest = latest
        self.before: datetime | None = None

    def find_latest_transcript(self, *, ticker: str, before=None):
        self.before = before
        return self.latest


class _FakeStatementService:
    def __init__(self, statements: list[KeyStatement]) -> None:
        self.statements = statements

    def list(self, document_id: str) -> list[KeyStatement]:
        return [s for s in self.statements if s.document_id == document_id]


def _statement(order: int, topic: str, text: str) -> KeyStatement:
    return KeyStatement(
        statement_id=f"investing:WMT:q1#s{order}",
        document_id="investing:WMT:q1",
        ticker="WMT",
        order=order,
        turn_index=order,
        speaker="John David Rainey",
        topic=topic,
        text=text,
    )


def _client(*, retriever=None, repository=None, statements=None) -> TestClient:
    app = main.create_app()
    if retriever is not None:
        app.state.analysis_service.external_retriever = retriever
    if repository is not None:
        app.state.transcript_repository = repository
    if statements is not None:
        app.state.transcript_statement_service = _FakeStatementService(statements)
    return TestClient(app)


def test_두_경로가_openapi_에_공개된다() -> None:
    paths = main.create_app().openapi()["paths"]
    assert "/v1/engine/assistant/news-search" in paths
    assert "/v1/engine/assistant/prior-call-statements" in paths


def test_뉴스_검색은_as_of_를_검색기_시점으로_넘기고_결과를_요약해_돌려준다() -> None:
    retriever = _FakeRetriever([_doc("d1", AS_OF - 3600)])
    client = _client(retriever=retriever)

    response = client.post(
        "/v1/engine/assistant/news-search",
        json={"ticker": "wmt", "query": "comp sales", "as_of_epoch": AS_OF, "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert retriever.calls[0]["chunk_timestamp"] == AS_OF
    assert retriever.calls[0]["ticker"] == "WMT"
    assert retriever.calls[0]["limit"] == 3
    assert retriever.calls[0]["lookback_days"] == 30
    hit = body["hits"][0]
    assert hit["doc_id"] == "d1"
    assert hit["source"] == "Reuters"
    assert hit["published_at"] == AS_OF - 3600
    assert len(hit["snippet"]) <= 600
    assert body["warnings"] == []


def test_as_of_이후에_발행된_기사는_검색기가_돌려줘도_뺀다() -> None:
    retriever = _FakeRetriever([_doc("before", AS_OF - 10), _doc("after", AS_OF + 86_400)])
    client = _client(retriever=retriever)

    body = client.post(
        "/v1/engine/assistant/news-search",
        json={"ticker": "WMT", "query": "price target", "as_of_epoch": AS_OF},
    ).json()

    assert [hit["doc_id"] for hit in body["hits"]] == ["before"]


def test_검색기_예외는_빈_결과와_경고로_돌려준다() -> None:
    client = _client(retriever=_FakeRetriever(error=RuntimeError("429")))

    response = client.post(
        "/v1/engine/assistant/news-search",
        json={"ticker": "WMT", "query": "comp sales", "as_of_epoch": AS_OF},
    )

    assert response.status_code == 200
    assert response.json()["hits"] == []
    assert response.json()["warnings"] == ["news_search_failed"]


def test_뉴스_검색_요청_범위를_검증한다() -> None:
    client = _client(retriever=_FakeRetriever())
    base = {"ticker": "WMT", "query": "x", "as_of_epoch": AS_OF}
    assert client.post("/v1/engine/assistant/news-search", json={**base, "top_k": 21}).status_code == 422
    assert client.post("/v1/engine/assistant/news-search", json={**base, "lookback_days": 0}).status_code == 422
    assert client.post("/v1/engine/assistant/news-search", json={**base, "query": " "}).status_code == 422
    assert client.post("/v1/engine/assistant/news-search", json={**base, "as_of_epoch": 0}).status_code == 422


def test_직전_콜_문장을_순서대로_돌려준다() -> None:
    repository = _FakeTranscriptRepository(
        {"document_id": "investing:WMT:q1", "fiscal_quarter": "Q1 FY2027", "published_at_epoch": AS_OF - 90 * 86_400}
    )
    statements = [
        _statement(2, "revenue", "Walmart US comp sales were up 4.1%."),
        _statement(1, "guidance", "We are reiterating our full year guidance."),
    ]
    client = _client(repository=repository, statements=statements)

    response = client.get(
        "/v1/engine/assistant/prior-call-statements", params={"ticker": "wmt", "before_epoch": AS_OF}
    )

    body = response.json()
    assert response.status_code == 200
    assert int(repository.before.timestamp()) == AS_OF
    assert body["available"] is True
    assert body["document_id"] == "investing:WMT:q1"
    assert body["fiscal_quarter"] == "Q1 FY2027"
    assert [s["order"] for s in body["statements"]] == [1, 2]
    assert body["statements"][0]["topic"] == "guidance"


def test_직전_콜이_없으면_available_false() -> None:
    client = _client(repository=_FakeTranscriptRepository(None), statements=[])

    body = client.get(
        "/v1/engine/assistant/prior-call-statements", params={"ticker": "WMT", "before_epoch": AS_OF}
    ).json()

    assert body["available"] is False
    assert body["statements"] == []
    assert body["warnings"] == ["prior_call_not_found"]


def test_직전_콜은_있지만_문장이_없으면_경고와_함께_빈_목록() -> None:
    repository = _FakeTranscriptRepository({"document_id": "investing:WMT:q1", "published_at_epoch": AS_OF - 1})
    client = _client(repository=repository, statements=[])

    body = client.get(
        "/v1/engine/assistant/prior-call-statements", params={"ticker": "WMT", "before_epoch": AS_OF}
    ).json()

    assert body["available"] is True
    assert body["statements"] == []
    assert body["warnings"] == ["key_statements_not_found"]


def test_직전_콜_조회를_지원하지_않는_저장소면_available_false() -> None:
    client = _client(repository=object(), statements=[])

    body = client.get(
        "/v1/engine/assistant/prior-call-statements", params={"ticker": "WMT", "before_epoch": AS_OF}
    ).json()

    assert body["available"] is False
    assert body["warnings"] == ["prior_call_lookup_unsupported"]
