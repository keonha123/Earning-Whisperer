from __future__ import annotations

import asyncio
import json

import pytest

from core.gemini_client import GenerationUsage
from models.request_models import SourceType
from models.transcript_statement_models import KeyStatement
from services import transcript_statement_diff
from services.transcript_diff_service import TranscriptDiffService
from services.transcript_statement_diff import select_candidates

DOC = "investing:WMT:q1"
CURRENT = (
    "We are raising our full-year guidance. We now expect adjusted EPS of $2.80 to $2.90, "
    "and comp sales growth of 4.5% in the quarter."
)


def _statement(order: int, topic: str, text: str) -> KeyStatement:
    return KeyStatement(
        statement_id=f"{DOC}#s{order}",
        document_id=DOC,
        ticker="WMT",
        order=order,
        turn_index=order,
        speaker="John David Rainey",
        topic=topic,
        text=text,
    )


STATEMENTS = [
    _statement(0, "guidance", "For the full year, we expect adjusted EPS of $2.75 to $2.85."),
    _statement(1, "revenue", "Comp sales in the U.S. grew 4.1%, led by transactions."),
    _statement(2, "capital", "We repurchased $1.2 billion of shares in the quarter."),
    _statement(3, "risk", "Tariff costs remain a headwind for the second half."),
]


class FakeTranscriptRepository:
    def find_latest_transcript(self, **kwargs):
        return {
            "document_id": DOC,
            "title": "WMT Q1 transcript",
            "published_at": "2026-05-15",
            "fiscal_quarter": "Q1_2027",
            "source_url": None,
        }

    def search_prior_transcript_chunks(self, **kwargs):
        raise AssertionError("chunk search should not run when key statements exist")


class FakeStatementService:
    def __init__(self, statements=None, *, fail=False) -> None:
        self.statements = STATEMENTS if statements is None else statements
        self.fail = fail
        self.requested: list[str] = []

    def list(self, document_id):
        self.requested.append(document_id)
        if self.fail:
            raise RuntimeError("qdrant down")
        return list(self.statements)


class FakeLlm:
    def __init__(self, payload=None, *, text=None, delay=0.0, error=None) -> None:
        self.payload = payload
        self.text = text
        self.delay = delay
        self.error = error
        self.prompts: list[str] = []
        self._response_cache: dict = {}

    def _cache_key(self, model, prompt, config):
        return (model, prompt)

    async def generate_content_with_metadata(self, *, model, contents, config):
        self.prompts.append(contents)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        text = self.text if self.text is not None else json.dumps(self.payload)
        self._response_cache[(model, contents)] = text
        return GenerationUsage(text=text)


def _service(monkeypatch, llm: FakeLlm, statement_service=None) -> TranscriptDiffService:
    monkeypatch.setattr("services.transcript_diff_service.gemini_client", llm)
    return TranscriptDiffService(FakeTranscriptRepository(), statement_service=statement_service or FakeStatementService())


async def _analyze(service: TranscriptDiffService, chunk: str = CURRENT):
    return await service.analyze(ticker="wmt", current_chunk=chunk, source_type=SourceType.EARNINGS_CALL, request_metadata={})


def _llm_items(*items):
    return {"items": list(items)}


GUIDANCE_ITEM = {
    "prior": [1],
    "current_claim": "We now expect adjusted EPS of $2.80 to $2.90",
    "topic": "guidance",
    "change_type": "improved",
    "summary_ko": "연간 조정 EPS 가이던스를 $2.75~2.85 에서 $2.80~2.90 으로 올렸습니다.",
    "confidence": 0.9,
    "risk_score": 0.1,
    "prior_claim": "Invented sentence that is not in the prior call.",
}


def test_select_candidates_keeps_related_statements_in_call_order() -> None:
    candidates = select_candidates(STATEMENTS, current_chunk=CURRENT, diff_topics=["guidance", "revenue"])

    assert [s.order for s in candidates] == [0, 1]


def test_select_candidates_returns_empty_for_unrelated_chunk() -> None:
    chunk = "Our associates delivered great service for our customers during the holidays across stores."

    assert select_candidates(STATEMENTS, current_chunk=chunk, diff_topics=["demand"]) == []


def test_select_candidates_caps_count_by_relevance() -> None:
    many = [_statement(i, "guidance", f"Adjusted EPS guidance item {i} for the full year.") for i in range(30)]

    candidates = select_candidates(many, current_chunk=CURRENT, diff_topics=["guidance"])

    assert len(candidates) == transcript_statement_diff.MAX_CANDIDATES
    assert [s.order for s in candidates] == sorted(s.order for s in candidates)


@pytest.mark.asyncio
async def test_prior_claim_is_stored_verbatim_statement_not_llm_text(monkeypatch) -> None:
    llm = FakeLlm(_llm_items(GUIDANCE_ITEM))
    service = _service(monkeypatch, llm)

    result = await _analyze(service)

    assert result["available"] is True
    assert result["warnings"] == []
    item = result["items"][0]
    assert item["prior_claim"] == STATEMENTS[0].text
    assert item["current_claim"] == "We now expect adjusted EPS of $2.80 to $2.90"
    assert item["change_type"] == "improved"
    assert item["evidence"][0]["snippet"] == STATEMENTS[0].text
    assert item["evidence"][0]["statement_id"] == f"{DOC}#s0"
    assert item["evidence"][0]["document_id"] == DOC
    assert "[1] (guidance; John David Rainey) For the full year" in llm.prompts[0]
    # 관련 없는 문장(자사주 매입)은 LLM 에 보이지 않는다.
    assert "repurchased" not in llm.prompts[0]


@pytest.mark.asyncio
async def test_item_with_two_prior_statements_joins_texts_in_call_order(monkeypatch) -> None:
    llm = FakeLlm(_llm_items({**GUIDANCE_ITEM, "prior": ["2", 1, 1, 99], "current_claim": CURRENT}))
    service = _service(monkeypatch, llm)

    result = await _analyze(service)

    item = result["items"][0]
    assert item["prior_claim"] == f"{STATEMENTS[0].text} … {STATEMENTS[1].text}"
    assert [e["statement_id"] for e in item["evidence"]] == [f"{DOC}#s0", f"{DOC}#s1"]


@pytest.mark.asyncio
async def test_items_with_invalid_statement_numbers_are_dropped(monkeypatch) -> None:
    llm = FakeLlm(_llm_items({**GUIDANCE_ITEM, "prior": [7]}, {**GUIDANCE_ITEM, "prior": None}, "bad"))
    service = _service(monkeypatch, llm)

    result = await _analyze(service)

    assert result["items"] == []
    assert "historical_transcript_diff_items_dropped:3" in result["warnings"]
    assert "no_comparable_prior_statement" in result["warnings"]


@pytest.mark.asyncio
async def test_paraphrased_current_claim_is_replaced_with_source_text(monkeypatch) -> None:
    llm = FakeLlm(_llm_items({**GUIDANCE_ITEM, "current_claim": "Walmart raised EPS outlook to 2.80-2.90"}))
    service = _service(monkeypatch, llm)

    result = await _analyze(service)

    assert result["items"][0]["current_claim"] == CURRENT
    assert "historical_transcript_diff_current_claim_replaced:1" in result["warnings"]


@pytest.mark.asyncio
async def test_empty_llm_items_returns_no_items_without_fallback(monkeypatch) -> None:
    llm = FakeLlm(_llm_items())
    service = _service(monkeypatch, llm)

    result = await _analyze(service)

    assert result["available"] is True
    assert result["items"] == []
    assert result["warnings"] == ["no_comparable_prior_statement"]


@pytest.mark.asyncio
async def test_unrelated_chunk_skips_llm(monkeypatch) -> None:
    llm = FakeLlm(_llm_items(GUIDANCE_ITEM))
    service = _service(monkeypatch, llm)

    result = await _analyze(service, "Customers responded well to the holiday assortment and pricing in stores, especially in grocery categories.")

    assert llm.prompts == []
    assert result["items"] == []
    assert result["warnings"] == ["no_related_prior_statement"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("llm", "reason"),
    [
        (FakeLlm(text="not json"), "invalid_response"),
        (FakeLlm(text=json.dumps({"summary": "no items key"})), "invalid_response"),
        (FakeLlm(error=RuntimeError("boom")), "llm_failed:RuntimeError"),
    ],
)
async def test_llm_failure_returns_no_invented_items(monkeypatch, llm, reason) -> None:
    service = _service(monkeypatch, llm)

    result = await _analyze(service)

    assert result["available"] is True
    assert result["items"] == []
    assert result["warnings"] == ["historical_transcript_diff_llm_failed", reason]


@pytest.mark.asyncio
async def test_llm_timeout_returns_no_items(monkeypatch) -> None:
    llm = FakeLlm(_llm_items(GUIDANCE_ITEM), delay=0.2)
    monkeypatch.setattr(transcript_statement_diff, "LLM_TIMEOUT_SECONDS", 0.01)
    service = _service(monkeypatch, llm)

    result = await _analyze(service)

    assert result["items"] == []
    assert result["warnings"] == ["historical_transcript_diff_llm_failed", "llm_timeout"]


@pytest.mark.asyncio
async def test_gemini_fallback_response_is_evicted_from_real_client_cache(monkeypatch) -> None:
    from core.gemini_client import GeminiClient

    client = GeminiClient()
    monkeypatch.setattr(
        client,
        "_generate_sync",
        lambda model, prompt, config: GenerationUsage(text=json.dumps({"direction": "NEUTRAL", "rationale": "Gemini fallback response"})),
    )
    monkeypatch.setattr("services.transcript_diff_service.gemini_client", client)
    service = TranscriptDiffService(FakeTranscriptRepository(), statement_service=FakeStatementService())

    result = await _analyze(service)

    assert result["warnings"] == ["historical_transcript_diff_llm_failed", "llm_failed:gemini_fallback"]
    assert client._response_cache == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("number", [0, -1, "0", 1.5, True])
async def test_out_of_range_statement_numbers_are_dropped(monkeypatch, number) -> None:
    service = _service(monkeypatch, FakeLlm(_llm_items({**GUIDANCE_ITEM, "prior": [number]})))

    result = await _analyze(service)

    assert result["items"] == []
    assert "historical_transcript_diff_items_dropped:1" in result["warnings"]


@pytest.mark.asyncio
async def test_float_and_bracketed_statement_numbers_are_accepted(monkeypatch) -> None:
    service = _service(monkeypatch, FakeLlm(_llm_items({**GUIDANCE_ITEM, "prior": [1.0, "[2]"], "current_claim": CURRENT})))

    result = await _analyze(service)

    assert [e["statement_id"] for e in result["items"][0]["evidence"]] == [f"{DOC}#s0", f"{DOC}#s1"]


@pytest.mark.asyncio
async def test_valid_item_survives_next_to_invalid_one(monkeypatch) -> None:
    service = _service(monkeypatch, FakeLlm(_llm_items({**GUIDANCE_ITEM, "prior": [7]}, GUIDANCE_ITEM)))

    result = await _analyze(service)

    assert len(result["items"]) == 1
    assert result["items"][0]["prior_claim"] == STATEMENTS[0].text
    assert result["warnings"] == ["historical_transcript_diff_items_dropped:1"]


@pytest.mark.asyncio
async def test_llm_values_are_normalized_to_backend_contract(monkeypatch) -> None:
    raw = {**GUIDANCE_ITEM, "confidence": "high", "risk_score": 1.7, "change_type": "better", "summary_ko": "", "topic": None}
    service = _service(monkeypatch, FakeLlm(_llm_items(raw)))

    item = (await _analyze(service))["items"][0]

    assert item["confidence"] == 0.55
    assert item["risk_score"] == 1.0
    assert item["change_type"] == "mixed"
    assert item["summary_ko"]
    assert item["topic"] == "guidance"


@pytest.mark.asyncio
async def test_items_are_capped(monkeypatch) -> None:
    service = _service(monkeypatch, FakeLlm(_llm_items(*[GUIDANCE_ITEM] * 5)))

    result = await _analyze(service)

    assert len(result["items"]) == transcript_statement_diff.MAX_ITEMS


@pytest.mark.asyncio
async def test_current_claim_is_taken_from_source_text(monkeypatch) -> None:
    chunk = "We’re raising our full-year guidance. We now expect adjusted EPS of $2.80 to $2.90."
    claim = "we're raising our FULL-YEAR guidance"
    service = _service(monkeypatch, FakeLlm(_llm_items({**GUIDANCE_ITEM, "current_claim": claim})))

    result = await _analyze(service, chunk)

    assert result["items"][0]["current_claim"] == "We're raising our full-year guidance"
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_too_short_current_claim_is_replaced(monkeypatch) -> None:
    service = _service(monkeypatch, FakeLlm(_llm_items({**GUIDANCE_ITEM, "current_claim": "EPS"})))

    result = await _analyze(service)

    assert result["items"][0]["current_claim"] == CURRENT
    assert "historical_transcript_diff_current_claim_replaced:1" in result["warnings"]


def test_select_candidates_single_overlap_needs_topic_match() -> None:
    statements = [
        _statement(0, "guidance", "Tariffs remain the main uncertainty."),
        _statement(1, "capital", "Tariffs were discussed with the board."),
    ]
    chunk = "Our guidance now assumes tariffs stay where they are for the rest of the period."

    candidates = select_candidates(statements, current_chunk=chunk, diff_topics=["guidance"])

    assert [s.order for s in candidates] == [0]


def test_select_candidates_ignores_units_years_and_integers() -> None:
    statements = [_statement(0, "capital", "We returned $4.5 billion to shareholders in fiscal 2026, about 3 times last period.")]
    chunk = "We invested $2 billion in associate wages in fiscal 2026 across 3 regions of the business."

    assert select_candidates(statements, current_chunk=chunk, diff_topics=["capex"]) == []


def test_select_candidates_matches_plural_possessive_and_hyphen_variants() -> None:
    statements = [_statement(0, "margin", "Walmart's gross margins expanded on full year mix.")]
    chunk = "Gross margin for Walmart expanded again this period on better full-year mix in general merchandise."

    assert [s.order for s in select_candidates(statements, current_chunk=chunk, diff_topics=[])] == [0]


@pytest.mark.asyncio
async def test_falls_back_to_chunk_search_when_no_statements_stored(monkeypatch) -> None:
    from tests.test_transcript_ingestion_and_diff import FakeTranscriptRepository as ChunkRepository

    async def _fake_generate(**kwargs):
        return GenerationUsage(text=json.dumps(_llm_items({"topic": "guidance", "change_type": "improved", "current_claim": "Guidance improved as AI demand accelerated and margins expanded.", "prior_claim": "Guidance was lowered and demand slowed in the prior quarter.", "evidence_indices": [1]})))

    monkeypatch.setattr("services.transcript_diff_service.gemini_client.generate_content_with_metadata", _fake_generate)
    statement_service = FakeStatementService([])
    service = TranscriptDiffService(ChunkRepository(), statement_service=statement_service)

    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Guidance improved as AI demand accelerated and margins expanded.",
        source_type=SourceType.EARNINGS_CALL,
        request_metadata={},
    )

    assert statement_service.requested == ["investing:NVDA:prev"]
    assert result["items"]
    assert result["warnings"] == ["key_statements_not_found"]


@pytest.mark.asyncio
async def test_statement_lookup_failure_falls_back_to_chunk_search(monkeypatch) -> None:
    from tests.test_transcript_ingestion_and_diff import FakeTranscriptRepository as ChunkRepository

    async def _fake_generate(**kwargs):
        return GenerationUsage(text=json.dumps(_llm_items({"topic": "guidance", "change_type": "improved", "current_claim": "Guidance improved as AI demand accelerated and margins expanded.", "prior_claim": "Guidance was lowered and demand slowed in the prior quarter.", "evidence_indices": [1]})))

    monkeypatch.setattr("services.transcript_diff_service.gemini_client.generate_content_with_metadata", _fake_generate)
    service = TranscriptDiffService(ChunkRepository(), statement_service=FakeStatementService(fail=True))

    result = await service.analyze(
        ticker="NVDA",
        current_chunk="Guidance improved as AI demand accelerated and margins expanded.",
        source_type=SourceType.EARNINGS_CALL,
        request_metadata={},
    )

    assert result["items"]
    assert result["warnings"] == ["key_statements_lookup_failed"]


def test_app_wires_statement_service_into_diff_service() -> None:
    import main

    app = main.create_app()

    assert app.state.transcript_diff_service.statement_service is app.state.transcript_statement_service


@pytest.mark.asyncio
async def test_statement_path_does_not_require_legacy_topic_keywords(monkeypatch) -> None:
    statements = [_statement(0, "segment", "International grew 6.2%, led by China and Flipkart.")]
    llm = FakeLlm(_llm_items({**GUIDANCE_ITEM, "current_claim": "International was up 7.9%"}))
    service = _service(monkeypatch, llm, FakeStatementService(statements))

    result = await _analyze(service, "International was up 7.9%, led by China and India.")

    assert len(llm.prompts) == 1
    assert result["items"][0]["prior_claim"] == statements[0].text


@pytest.mark.asyncio
async def test_new_claim_items_are_dropped(monkeypatch) -> None:
    service = _service(monkeypatch, FakeLlm(_llm_items({**GUIDANCE_ITEM, "change_type": "new_claim"}, GUIDANCE_ITEM)))

    result = await _analyze(service)

    assert [item["change_type"] for item in result["items"]] == ["improved"]
    assert "historical_transcript_diff_items_dropped:1" in result["warnings"]

@pytest.mark.parametrize("current,prior,blocked", [
    ("Sam's Club U.S. delivered comps of 4.4%", "And Sam's Club US club fulfilled delivery sales grew more than 90% in Q1.", True),
    ("International was up 7.9%", "These sales results improved economics in the International segment, where Asia led to more than 10% operating income growth.", True),
    ("International was up 7.9%", "International grew 6.2%, led by China and Flipkart.", False),
    ("We've expanded delivery into 38 markets in the U.S.", "We can reach 60% of the US population in 30 minutes.", True),
    ("Operating income growth included 750 basis points of tariff refunds.", "Higher fuel costs reduced operating income growth by 250 basis points.", True),
    ("Sam's Club comparable sales grew 4.4%.", "Sam's Club fulfilled delivery sales grew 90%.", True),
    ("International sales grew 7.9%.", "Asia operating income grew 10%.", True),
    ("International sales grew 7.9%.", "International revenue grew 6.1%.", False),
    ("Sam's Club comparable sales grew 4.4%.", "Sam's Club comp sales grew 4.1%.", False),
    ("International sales grew 7.9%.", "U.S. sales grew 6.1%.", True),
    ("Operating margin improved 10%.", "Operating margin improved 10 basis points.", True),
])
def test_explicit_metric_conflicts_override_model_confidence(current, prior, blocked):
    items, warnings = transcript_statement_diff.normalize_items(
        [{"prior": [1], "current_claim": current, "change_type": "improved", "confidence": 1.0}],
        current_chunk=current, candidates=[_statement(0, "revenue", prior)], previous_document={},
    )
    assert bool(items) is not blocked
    if items:
        assert items[0]["prior_claim"] == prior
        assert items[0]["current_claim"] == current
    else:
        assert warnings == ["historical_transcript_diff_items_dropped:1"]

@pytest.mark.parametrize("current,prior,blocked", [
    ("Sam’s Club comparable sales grew 4.4%.", "Sam’s Club fulfilled delivery sales grew 90%.", True),
    ("Walmart U.S. comparable sales grew 4.4%.", "Sam’s Club U.S. comparable sales grew 4.1%.", True),
    ("Sam’s Club U.S. comparable sales grew 4.4%.", "Sam's Club US comp sales grew 4.1%.", False),
    ("Operating margin improved 10 percent.", "Operating margin improved 10 percent points.", True),
    ("Operating margin improved 10%.", "Operating margin improved 10%p.", True),
    ("Operating margin improved 10 percentage points.", "Operating margin improved 10 basis points.", True),
    ("International sales grew 4.4%, helping us.", "U.S. sales grew 4.1%.", True),
])
def test_explicit_conflicts_normalize_punctuation_and_distinguish_units(current, prior, blocked):
    assert transcript_statement_diff.explicit_comparison_conflict(current, prior) is blocked
