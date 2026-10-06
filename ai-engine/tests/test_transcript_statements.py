"""직전 콜 핵심 문장 추출 · 저장 (#124)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import pytest
from types import SimpleNamespace

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

import main
from config import Settings
from core.gemini_client import GeminiClient
from models.evidence_models import EvidenceDocument, EvidenceSourceType
from models.ingestion_models import EarningsTranscriptIngestItem, TranscriptSpeakerTurn
from models.transcript_statement_models import KeyStatement
from repositories.qdrant_evidence_repository import QdrantEvidenceRepository
from repositories.transcript_statement_repository import (
    InMemoryTranscriptStatementRepository,
    QdrantTranscriptStatementRepository,
)
from services import transcript_statement_extraction_service as extraction_module
from services.transcript_statement_extraction_service import TranscriptStatementExtractionService
from services.transcript_statement_service import TranscriptStatementService

CFO = "John David Rainey"
GUIDANCE = "We are reiterating our full year guidance of constant currency sales growth between 3.5% and 4.5%."
COMPS = "Walmart US comp sales were up 4.1% despite a 100-basis point headwind from maximum fair pricing legislation in pharmacy."


class FakeLlmClient:
    def __init__(self, *payloads, delay: float = 0.0) -> None:
        self.payloads = list(payloads)
        self.delay = delay
        self.calls = []

    async def generate_content_with_metadata(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        payload = self.payloads.pop(0) if self.payloads else {"statements": []}
        if callable(payload):
            payload = payload(kwargs["contents"])
        if isinstance(payload, Exception):
            raise payload
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return SimpleNamespace(text=text)


def _turns() -> list[TranscriptSpeakerTurn]:
    return [
        TranscriptSpeakerTurn(speaker="Operator", text="Good morning and welcome to the call.", section="prepared"),
        TranscriptSpeakerTurn(speaker=CFO, text=f"Thank you. {COMPS} Fashion performed well.", section="prepared"),
        TranscriptSpeakerTurn(speaker=CFO, text=f"Looking ahead to the year. {GUIDANCE} We expect EPS of $2.75 to $2.85.", section="prepared"),
    ]


def _extract(llm: FakeLlmClient, turns=None, **kwargs):
    service = TranscriptStatementExtractionService(llm_client=llm, settings=Settings(), **kwargs)
    return asyncio.run(service.extract(document_id="factset:WMT:q1", ticker="wmt", turns=turns or _turns()))


def test_extraction_passes_batch_deadline_to_provider():
    llm = FakeLlmClient({"statements": []})
    _extract(llm, batch_timeout_seconds=47.0)
    assert llm.calls[0]["config"]["timeout_seconds"] == 47.0


def test_원문에_있는_문장만_원문_순서대로_저장한다():
    llm = FakeLlmClient({"statements": [
        {"turn": 2, "topic": "guidance", "text": GUIDANCE},
        {"turn": 1, "topic": "revenue", "text": COMPS},
    ]})

    result = _extract(llm)

    assert [s.text for s in result.statements] == [COMPS, GUIDANCE]
    assert [s.order for s in result.statements] == [0, 1]
    assert [s.statement_id for s in result.statements] == ["factset:WMT:q1#s0", "factset:WMT:q1#s1"]
    first = result.statements[0]
    assert (first.ticker, first.turn_index, first.speaker, first.section, first.topic) == ("WMT", 1, CFO, "prepared", "revenue")
    assert result.rejected_count == 0
    assert result.warnings == []


def test_숫자를_바꾼_문장은_원문에_없으므로_버린다():
    # 실측에서 LLM 이 Q1 기존점 매출 4.1% 를 3% 로 바꿔 쓴 적이 있다.
    altered = COMPS.replace("4.1%", "3%")
    llm = FakeLlmClient({"statements": [{"turn": 1, "topic": "revenue", "text": altered}]})

    result = _extract(llm)

    assert result.statements == []
    assert result.rejected_count == 1


def test_둥근_따옴표와_공백_차이는_같은_문장으로_본다():
    turns = [TranscriptSpeakerTurn(speaker=CFO, text="Sam’s Club   comp sales grew 6.8%   excluding fuel.")]
    llm = FakeLlmClient({"statements": [{"turn": 0, "topic": "revenue", "text": "Sam's Club comp sales grew 6.8% excluding fuel."}]})

    result = _extract(llm, turns=turns)

    assert [s.text for s in result.statements] == ["Sam's Club comp sales grew 6.8% excluding fuel."]


def test_배치_밖의_발언_번호_짧은_문장_중복은_버리고_모르는_주제는_other():
    llm = FakeLlmClient({"statements": [
        {"turn": 7, "topic": "revenue", "text": COMPS},
        {"turn": 1, "topic": "revenue", "text": "Thank you."},
        {"turn": 1, "topic": "segment", "text": COMPS},
        {"turn": 1, "topic": "revenue", "text": COMPS},
        {"turn": 2, "topic": "weather", "text": GUIDANCE},
        "not an object",
    ]})

    result = _extract(llm)

    assert [(s.text, s.topic) for s in result.statements] == [(COMPS, "segment"), (GUIDANCE, "other")]
    assert result.rejected_count == 3


def test_긴_원문은_여러_배치로_나누고_긴_발언은_문장_경계에서_자른다(monkeypatch):
    monkeypatch.setattr(extraction_module, "BATCH_MAX_CHARS", 300)
    long_turn = " ".join(f"Sentence number {i} has some words." for i in range(20))
    turns = [TranscriptSpeakerTurn(speaker=CFO, text=long_turn), TranscriptSpeakerTurn(speaker=CFO, text=GUIDANCE)]
    llm = FakeLlmClient()

    _extract(llm, turns=turns)

    prompts = [call["contents"] for call in llm.calls]
    assert len(prompts) >= 3
    assert all(len(p.split("Transcript:\n", 1)[1]) < 300 + 200 for p in prompts)
    assert any(GUIDANCE in p for p in prompts)


def _guidance_only(prompt: str):
    """GUIDANCE 가 든 배치에서만 그 문장을 고른다. 배치 경계가 바뀌어도 테스트가 흔들리지 않게 한다."""
    found = GUIDANCE in prompt
    return {"statements": [{"turn": 2, "topic": "guidance", "text": GUIDANCE}] if found else []}


def test_배치가_실패해도_나머지_배치는_계속한다(monkeypatch):
    monkeypatch.setattr(extraction_module, "BATCH_MAX_CHARS", 150)
    llm = FakeLlmClient(RuntimeError("boom"), "not json", *[_guidance_only] * 5)

    result = _extract(llm)

    assert len(llm.calls) >= 3
    assert [s.text for s in result.statements] == [GUIDANCE]
    assert result.warnings == ["key_statement_batch_internal_error:0", "key_statement_batch_invalid_response:1"]


def test_시간_초과():
    result = _extract(FakeLlmClient({"statements": []}, delay=0.5), batch_timeout_seconds=0.05)

    assert result.warnings == ["key_statement_batch_timeout:0"]


def test_gemini_client_폴백은_호출_실패로_보고_캐시에서_지운다(monkeypatch):
    client = GeminiClient()
    calls = []

    def fake_sdk(model, prompt, config):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return json.dumps({"statements": [{"turn": 2, "topic": "guidance", "text": GUIDANCE}]}), {"total_tokens": 2}

    client._generate_with_modern_sdk = fake_sdk
    monkeypatch.setattr("core.gemini_client.get_settings", lambda: Settings(GEMINI_RESPONSE_CACHE_ENABLED=True))
    service = TranscriptStatementExtractionService(llm_client=client, settings=Settings())

    first = asyncio.run(service.extract(document_id="d", ticker="WMT", turns=_turns()))
    assert first.warnings == ["key_statement_batch_llm_failed:0"]
    assert client._response_cache == {}

    second = asyncio.run(service.extract(document_id="d", ticker="WMT", turns=_turns()))
    assert [s.text for s in second.statements] == [GUIDANCE]
    assert len(calls) == 2


def _item(**overrides) -> EarningsTranscriptIngestItem:
    data = {
        "provider": "factset",
        "provider_id": "q1",
        "ticker": "wmt",
        "title": "Walmart Q1",
        "published_at": datetime(2026, 5, 21, tzinfo=UTC),
        "fiscal_quarter": "FY2027Q1",
        "content": "full text",
        "speaker_turns": [t.model_dump() for t in _turns()],
    }
    data.update(overrides)
    return EarningsTranscriptIngestItem.model_validate(data)


def test_서비스는_적재와_같은_document_id_로_저장한다():
    llm = FakeLlmClient({"statements": [{"turn": 2, "topic": "guidance", "text": GUIDANCE}]})
    repo = InMemoryTranscriptStatementRepository()
    service = TranscriptStatementService(extractor=TranscriptStatementExtractionService(llm_client=llm, settings=Settings()), repository=repo)

    result = asyncio.run(service.ingest([_item()]))

    assert result.counts == {"factset:WMT:q1": 1}
    saved = repo.list("factset:WMT:q1")[0]
    assert (saved.published_at_epoch, saved.fiscal_quarter) == (int(datetime(2026, 5, 21, tzinfo=UTC).timestamp()), "FY2027Q1")


def test_일부_배치가_실패하면_이전에_저장된_문장을_지키고_처음이면_일부라도_저장한다(monkeypatch):
    monkeypatch.setattr(extraction_module, "BATCH_MAX_CHARS", 150)
    repo = InMemoryTranscriptStatementRepository()

    def service(*payloads):
        return TranscriptStatementService(
            extractor=TranscriptStatementExtractionService(llm_client=FakeLlmClient(*payloads), settings=Settings()),
            repository=repo,
        )

    first = asyncio.run(service(RuntimeError("boom"), *[_guidance_only] * 5).ingest([_item()]))
    assert first.counts == {"factset:WMT:q1": 1}

    second = asyncio.run(service(RuntimeError("boom")).ingest([_item()]))
    assert second.counts == {}
    assert "key_statements_kept_previous:batch_failed:factset:WMT:q1" in second.warnings
    assert [s.text for s in repo.list("factset:WMT:q1")] == [GUIDANCE]


def _statement(document_id: str, order: int, text: str) -> KeyStatement:
    return KeyStatement(
        statement_id=f"{document_id}#s{order}", document_id=document_id, ticker="WMT",
        order=order, turn_index=order, topic="guidance", text=text,
    )


def test_qdrant_저장소는_다시_넣으면_옛_문장을_지우고_기존_트랜스크립트_조회와_섞이지_않는다():
    client = QdrantClient(location=":memory:")
    transcripts = QdrantEvidenceRepository(
        client=client, collection_name="transcripts", store_name="transcript", embedding_dimension=64,
    )
    transcripts.add_documents([
        EvidenceDocument(
            document_id="factset:WMT:q1", ticker="WMT", source_type=EvidenceSourceType.EARNINGS_CALL,
            source="factset", title="Walmart Q1", published_at=datetime(2026, 5, 21, tzinfo=UTC),
            content=GUIDANCE, reliability_score=0.88, metadata={"provider": "factset", "provider_id": "q1"},
        )
    ])
    repo = QdrantTranscriptStatementRepository.sharing(transcripts)

    repo.replace("factset:WMT:q1", [_statement("factset:WMT:q1", i, f"Old statement number {i} about guidance.") for i in range(3)])
    repo.replace("factset:WMT:q1", [_statement("factset:WMT:q1", 1, COMPS), _statement("factset:WMT:q1", 0, GUIDANCE)])
    repo.replace("factset:WMT:q0", [_statement("factset:WMT:q0", 0, "Another call statement about guidance.")])

    assert [s.text for s in repo.list("factset:WMT:q1")] == [GUIDANCE, COMPS]
    chunks = transcripts.search_prior_transcript_chunks(ticker="WMT", query="guidance", document_id="factset:WMT:q1", top_k=10)
    assert [c.snippet for c in chunks] == [GUIDANCE]
    latest = transcripts.find_latest_transcript(ticker="WMT")
    assert latest["document_id"] == "factset:WMT:q1"


def test_failed_statement_upsert_preserves_previous_document(monkeypatch):
    client = QdrantClient(location=":memory:")
    transcripts = QdrantEvidenceRepository(client=client, collection_name="statements_failure", store_name="transcript", embedding_dimension=64)
    repo = QdrantTranscriptStatementRepository.sharing(transcripts)
    old = _statement("factset:WMT:q1", 0, GUIDANCE)
    repo.replace(old.document_id, [old])

    def fail(**kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(client, "upsert", fail)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        repo.replace(old.document_id, [_statement(old.document_id, 1, COMPS)])
    assert repo.list(old.document_id) == [old]
    with pytest.raises(ValueError, match="does not match"):
        repo.replace("different-document", [old])
    assert repo.list(old.document_id) == [old]
    client.close()


def test_적재_엔드포인트가_핵심_문장_수를_함께_돌려준다(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")
    app = main.create_app()
    app.state.transcript_statement_service = TranscriptStatementService(
        extractor=TranscriptStatementExtractionService(
            llm_client=FakeLlmClient({"statements": [{"turn": 2, "topic": "guidance", "text": GUIDANCE}]}),
            settings=Settings(),
        ),
        repository=InMemoryTranscriptStatementRepository(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/integration/collector/earnings-transcripts",
        json={"items": [_item().model_dump(mode="json")]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["key_statement_counts"] == {"factset:WMT:q1": 1}
    # 문장이 트랜스크립트와 같은 document_id 로 저장되어야 대조가 찾는다.
    assert set(body["key_statement_counts"]) <= set(body["document_ids"])


def test_사회자와_애널리스트_질문은_고르지_못하게_한다():
    turns = [
        TranscriptSpeakerTurn(speaker="Operator", text="Our first question comes from Greg Melich with Evercore.", section="qa"),
        TranscriptSpeakerTurn(speaker="Greg Melich", text="Traffic was up 3% at Walmart US and 6% at Sam's. How sustainable is that?", section="qa"),
        TranscriptSpeakerTurn(speaker=CFO, text=f"Thanks, Greg. {COMPS}", section="qa"),
        TranscriptSpeakerTurn(speaker="Greg Melich", text="And a follow-up: margins were up 29 basis points in the US?", section="qa"),
    ]
    llm = FakeLlmClient({"statements": [
        {"turn": 1, "topic": "revenue", "text": "Traffic was up 3% at Walmart US and 6% at Sam's."},
        {"turn": 2, "topic": "revenue", "text": COMPS},
        {"turn": 3, "topic": "margin", "text": "margins were up 29 basis points in the US?"},
    ]})

    result = _extract(llm, turns=turns)

    assert [s.text for s in result.statements] == [COMPS]
    assert result.rejected_count == 2
    prompt = llm.calls[0]["contents"]
    assert "[T1] (qa, NOT management - do not select) Greg Melich" in prompt
    assert "[T2] (qa) John David Rainey" in prompt


def test_사회자가_소개한_경영진_마무리_발언은_경영진으로_본다():
    turns = [
        TranscriptSpeakerTurn(speaker="John R. Furner", text="Welcome. We had a strong quarter overall.", section="prepared"),
        TranscriptSpeakerTurn(speaker="Operator", text="Our first question comes from Kate.", section="qa"),
        TranscriptSpeakerTurn(speaker="Kate McShane", text="Can you talk about comps?", section="qa"),
        TranscriptSpeakerTurn(speaker=CFO, text=COMPS, section="qa"),
        TranscriptSpeakerTurn(speaker="Operator", text="I'd now like to turn the call back to John for closing remarks.", section="qa"),
        TranscriptSpeakerTurn(speaker="John R. Furner", text="Delivery under 30 minutes now reaches 60% of the US population.", section="qa"),
    ]
    llm = FakeLlmClient({"statements": [
        {"turn": 3, "topic": "revenue", "text": COMPS},
        {"turn": 5, "topic": "strategy", "text": "Delivery under 30 minutes now reaches 60% of the US population."},
    ]})

    result = _extract(llm, turns=turns)

    assert [s.speaker for s in result.statements] == [CFO, "John R. Furner"]


def test_구간_정보가_없으면_애널리스트_필터가_꺼졌다고_경고한다():
    turns = [TranscriptSpeakerTurn(speaker=CFO, text=GUIDANCE)]

    result = _extract(FakeLlmClient({"statements": []}), turns=turns)

    assert result.warnings == ["key_statement_no_section_analyst_filter_off"]


def test_문장_조각을_고르면_앞뒤_문장_경계까지_넓혀_저장한다():
    turns = [TranscriptSpeakerTurn(
        speaker=CFO,
        text="Thanks. We do not expect tariffs to pressure margins by 50 basis points this year. Next topic.",
        section="prepared",
    )]
    llm = FakeLlmClient({"statements": [
        {"turn": "T0", "topic": "risk", "text": "expect tariffs to pressure margins by 50 basis points"},
    ]})

    result = _extract(llm, turns=turns)

    assert [s.text for s in result.statements] == ["We do not expect tariffs to pressure margins by 50 basis points this year."]


def test_같은_문장의_두_조각은_한_문장으로_합친다():
    sentence = "For Q2, we expect EPS of $0.72 to $0.74 and full year EPS in the range of $2.75 to $2.85."
    turns = [TranscriptSpeakerTurn(speaker=CFO, text=f"Okay. {sentence} Thanks.", section="prepared")]
    llm = FakeLlmClient({"statements": [
        {"turn": 0, "topic": "guidance", "text": "For Q2, we expect EPS of $0.72 to $0.74"},
        {"turn": 0, "topic": "guidance", "text": "full year EPS in the range of $2.75 to $2.85."},
    ]})

    result = _extract(llm, turns=turns)

    assert [s.text for s in result.statements] == [sentence]


class _FailingListRepository(InMemoryTranscriptStatementRepository):
    def list(self, document_id):
        raise RuntimeError("qdrant down")


def _service_with(repo, *payloads):
    return TranscriptStatementService(
        extractor=TranscriptStatementExtractionService(llm_client=FakeLlmClient(*payloads), settings=Settings()),
        repository=repo,
    )


def test_이전_문장_조회가_실패해도_예외_없이_경고로_돌려준다():
    result = asyncio.run(_service_with(_FailingListRepository(), RuntimeError("boom")).ingest([_item()]))

    assert result.counts == {}
    assert "key_statement_store_failed:factset:WMT:q1" in result.warnings


def test_한_문장도_못_건지면_이전_문장을_지킨다():
    repo = InMemoryTranscriptStatementRepository()
    asyncio.run(_service_with(repo, {"statements": [{"turn": 2, "topic": "guidance", "text": GUIDANCE}]}).ingest([_item()]))

    second = asyncio.run(_service_with(repo, {"statements": [{"turn": 2, "topic": "guidance", "text": "Made up sentence about 9% growth."}]}).ingest([_item()]))

    assert second.counts == {}
    assert "key_statements_kept_previous:empty:factset:WMT:q1" in second.warnings
    assert [s.text for s in repo.list("factset:WMT:q1")] == [GUIDANCE]


def test_본문이_비어_적재되지_않는_항목은_문장도_저장하지_않는다():
    repo = InMemoryTranscriptStatementRepository()
    llm = FakeLlmClient({"statements": [{"turn": 2, "topic": "guidance", "text": GUIDANCE}]})
    service = TranscriptStatementService(extractor=TranscriptStatementExtractionService(llm_client=llm, settings=Settings()), repository=repo)

    result = asyncio.run(service.ingest([_item(content="   ")]))

    assert result.counts == {}
    assert llm.calls == []


def _app_with(statement_service):
    app = main.create_app()
    app.state.transcript_statement_service = statement_service
    return TestClient(app)


def test_추출이_실패해도_적재_응답은_200_이고_경고가_합쳐진다(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")
    client = _app_with(_service_with(InMemoryTranscriptStatementRepository(), RuntimeError("boom")))

    body = client.post("/api/v1/integration/collector/earnings-transcripts", json={"items": [_item().model_dump(mode="json")]}).json()

    assert body["accepted_count"] == 1
    assert body["key_statement_counts"] == {"factset:WMT:q1": 0}
    assert "key_statement_batch_internal_error:0:factset:WMT:q1" in body["warnings"]


def test_추출_단계가_통째로_실패해도_적재_응답은_200(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")

    class Broken:
        async def ingest(self, items):
            raise RuntimeError("boom")

    client = _app_with(Broken())

    response = client.post("/api/v1/integration/collector/earnings-transcripts", json={"items": [_item().model_dump(mode="json")]})

    assert response.status_code == 200
    assert response.json()["accepted_count"] == 1
    assert response.json()["warnings"] == ["key_statement_extraction_failed"]
