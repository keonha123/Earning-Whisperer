from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.routers.transcript_assistant import router
from core.gemini_client import GenerationUsage
from models.evidence_models import EvidenceCitation, EvidenceSourceType
from models.transcript_assistant_models import TranscriptAskRequest, TranscriptTranslateRequest
from services.transcript_assistant_service import TranscriptAssistantService
from services.transcript_glossary import get_glossary


def settings(**kwargs):
    return SimpleNamespace(**dict({"gemini_api_key": "test-key", "gemini_primary_model": "test-model",
                                  "transcript_translation_timeout_seconds": .1, "transcript_qa_timeout_seconds": .2}, **kwargs))


def question(**kwargs):
    return TranscriptAskRequest(**dict({"ticker": "nvda", "call_id": "call-1", "segment_sequences": [81],
        "segment_texts": ["Revenue increased 20% because demand grew."],
        "question": "매출이 증가한 이유는 무엇인가요?", "as_of": datetime(2026, 1, 5, 12, tzinfo=UTC)}, **kwargs))


def fake_model(monkeypatch, value):
    configs = []
    async def generate(**kwargs):
        configs.append(kwargs["config"])
        return GenerationUsage(text=json.dumps(value, ensure_ascii=False))
    monkeypatch.setattr("services.transcript_assistant_service.gemini_client.generate_content_with_metadata", generate)
    return configs


@pytest.mark.asyncio
async def test_provider_outage_is_distinguished_from_unsupported_answer(monkeypatch):
    async def unavailable(**kwargs):
        return GenerationUsage(text='{"direction":"NEUTRAL"}', is_fallback=True, error_code="http_503")
    monkeypatch.setattr("services.transcript_assistant_service.gemini_client.generate_content_with_metadata", unavailable)
    service = TranscriptAssistantService(settings())
    translated = await service.translate(TranscriptTranslateRequest(ticker="MU", call_id="c", sequence=0, text="Revenue grew."))
    answer = await service.ask(question())
    assert not translated.available and translated.warnings == ["translation_provider_http_503"]
    assert answer.refusal_reason == "model_unavailable" and answer.warnings == ["qa_provider_http_503"]
    assert answer.evidence and not answer.answer_ko


def supported(**kwargs):
    return dict({"verdict": "supported", "answer_ko": "수요가 늘어 매출이 증가했습니다.",
                 "citations": [{"evidence_index": 0, "quote": "because demand grew."}]}, **kwargs)


@pytest.mark.asyncio
async def test_translation_preserves_identity_numbers_and_negation(monkeypatch):
    configs = fake_model(monkeypatch, {"text_ko": "매출은 $5 billion이며 20% 감소하지 않았습니다.", "meaning_preserved": True})
    request = TranscriptTranslateRequest(ticker="nvda", call_id="call-1", sequence=3,
                                         text="Revenue is $5 billion and did not decline 20%.")
    result = await TranscriptAssistantService(settings()).translate(request)
    assert result.available and result.sequence == 3 and result.call_id == "call-1" and result.ticker == "NVDA"
    assert result.original_text == request.text

    assert len(configs) == 1 and configs[0]["thinking_level"] == "minimal"


@pytest.mark.asyncio
async def test_remote_translation_terms_override_curated_without_session(monkeypatch):
    fake_model(monkeypatch, {"text_ko": "수익은 20% 증가했습니다.", "meaning_preserved": True})
    request = TranscriptTranslateRequest(ticker="nvda", sequence=3, text="Revenue grew 20%.",
        terms=[{"term": "Revenue", "ko": "수익"}, {"term": "revenue", "ko": "매출"}])
    result = await TranscriptAssistantService(settings()).translate(request)
    assert result.available and result.call_id is None
    assert result.terms_used == ["Revenue"] and result.original_text == request.text
    with pytest.raises(ValueError):
        question(call_id=None)


@pytest.mark.asyncio
async def test_remote_empty_terms_does_not_force_local_glossary(monkeypatch):
    fake_model(monkeypatch, {"text_ko": "수익은 증가했습니다.", "meaning_preserved": True})
    result = await TranscriptAssistantService(settings()).translate(TranscriptTranslateRequest(
        ticker="NVDA", sequence=0, text="Revenue grew.", terms=[]))
    assert result.available and result.terms_used == []


@pytest.mark.asyncio
async def test_remote_terms_do_not_count_overlapping_korean_twice(monkeypatch):
    fake_model(monkeypatch, {"text_ko": "기존점 매출이 증가했습니다.", "meaning_preserved": True})
    result = await TranscriptAssistantService(settings()).translate(TranscriptTranslateRequest(
        ticker="WMT", sequence=0, text="Revenue and comparable sales grew.",
        terms=[{"term": "revenue", "ko": "매출"}, {"term": "comparable sales", "ko": "기존점 매출"}]))
    assert not result.available and "translation_glossary_mismatch:revenue" in result.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize("source,translated,accepted", [
    ("Revenue increased twenty percent.", "매출은 20% 증가했습니다.", True),
    ("Margin improved five percentage points.", "마진은 5퍼센트포인트 개선됐습니다.", True),
    ("Margin improved five percentage points.", "마진은 5% 개선됐습니다.", False),
    ("Revenue increased twenty percent.", "매출은 30% 증가했습니다.", False),
    ("Revenue was one hundred and twenty-five million USD.", "매출은 125 million USD였습니다.", True),
    ("Revenue was five million USD.", "매출은 5 billion USD였습니다.", False),
    ("Growth was minus twenty percent.", "성장률은 -20%였습니다.", True),
    ("Growth was minus twenty percent.", "성장률은 20%였습니다.", False),
])
async def test_spoken_numeric_value_and_percentage_point_preservation(monkeypatch, source, translated, accepted):
    fake_model(monkeypatch, {"text_ko": translated, "meaning_preserved": True})
    result = await TranscriptAssistantService(settings()).translate(TranscriptTranslateRequest(
        ticker="NVDA", call_id="spoken", sequence=0, text=source, terms=[]))
    assert result.available is accepted
    if not accepted:
        assert result.warnings == ["translation_numeric_or_unit_mismatch"]


@pytest.mark.asyncio
@pytest.mark.parametrize("translated,warning", [
    ("매출은 $6 billion입니다.", "translation_numeric_or_unit_mismatch"),
    ("매출은 $5 million입니다.", "translation_numeric_or_unit_mismatch"),
    ("매출은 $5 billion입니다.", "translation_negation_mismatch"),
])
async def test_translation_rejects_changed_numbers_units_negation(monkeypatch, translated, warning):
    fake_model(monkeypatch, {"text_ko": translated, "meaning_preserved": True})
    result = await TranscriptAssistantService(settings()).translate(TranscriptTranslateRequest(
        ticker="NVDA", call_id="c", sequence=1, text="Revenue is not $5 billion."))
    assert not result.available and result.text_ko is None and warning in result.warnings


@pytest.mark.asyncio
async def test_missing_key_does_not_fabricate_translation_or_answer(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    async def fail(**kwargs):
        raise AssertionError("No model should run without a key")
    monkeypatch.setattr("services.transcript_assistant_service.gemini_client.generate_content_with_metadata", fail)
    service = TranscriptAssistantService(settings(gemini_api_key=""))
    translated = await service.translate(TranscriptTranslateRequest(ticker="NVDA", call_id="c", sequence=1, text="Revenue grew."))
    answer = await service.ask(question())
    assert not translated.available and translated.text_ko is None
    assert answer.refusal_reason == "model_unavailable" and answer.evidence and answer.answer_ko is None


@pytest.mark.asyncio
async def test_translation_and_qa_timeout_keep_original_and_evidence(monkeypatch):
    async def slow(**kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr("services.transcript_assistant_service.gemini_client.generate_content_with_metadata", slow)
    service = TranscriptAssistantService(settings(transcript_translation_timeout_seconds=.01, transcript_qa_timeout_seconds=.01))
    translated = await service.translate(TranscriptTranslateRequest(ticker="NVDA", call_id="c", sequence=1, text="Revenue grew."))
    answer = await service.ask(question())
    assert translated.original_text == "Revenue grew." and translated.warnings == ["translation_timeout"]
    assert answer.refusal_reason == "timeout" and len(answer.evidence) == 1 and not answer.available


@pytest.mark.asyncio
async def test_grounded_answer_requires_exact_selected_citation(monkeypatch):
    configs = fake_model(monkeypatch, supported())
    result = await TranscriptAssistantService(settings()).ask(question())
    assert result.available and result.citations[0].evidence_index == 0
    assert result.evidence[0].metadata["sequence"] == 81

    assert len(configs) == 2  # Candidate and independent verifier both remain required.
    assert all(config["thinking_level"] == "minimal" for config in configs)


@pytest.mark.asyncio
async def test_default_qa_deadline_leaves_verification_budget_after_retry(monkeypatch):
    from config import Settings
    import services.transcript_assistant_service as module
    clock = [100.0]
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(
        get_running_loop=lambda: SimpleNamespace(time=lambda: clock[0])))
    service = TranscriptAssistantService(settings(
        transcript_qa_timeout_seconds=Settings(_env_file=None).transcript_qa_timeout_seconds))
    budgets = []
    async def generate(prompt, timeout):
        budgets.append(timeout)
        # Observed timed-out attempt + backoff + successful retry consume 11.6s.
        clock[0] += 11.6 if len(budgets) == 1 else 4.0
        assert timeout >= 4.0
        return supported()
    monkeypatch.setattr(service, "_generate", generate)
    result = await service.ask(question())
    assert result.available and len(budgets) == 2
    assert budgets[1] == pytest.approx(budgets[0] - 11.6)


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [
    supported(citations=[]), supported(citations=[{"evidence_index": 99, "quote": "demand"}]),
    supported(citations=[{"evidence_index": 0, "quote": "fabricated quote"}]),
    {"direction": "NEUTRAL", "confidence": 0.0},
])
async def test_uncited_fabricated_and_generic_fallback_answers_rejected(monkeypatch, output):
    fake_model(monkeypatch, output)
    result = await TranscriptAssistantService(settings()).ask(question())
    assert not result.available and result.answer_ko is None and result.evidence
    assert result.refusal_reason == "invalid_or_unsupported_response"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Should I buy NVDA?", "지금 매수해야 하나요?", "지금 사야 할까요?", "목표주가를 알려줘", "오늘 날씨는?"])
async def test_deterministic_refusals_do_not_call_model(monkeypatch, text):
    async def fail(**kwargs):
        raise AssertionError("Refusal should not invoke a model")
    monkeypatch.setattr("services.transcript_assistant_service.gemini_client.generate_content_with_metadata", fail)
    result = await TranscriptAssistantService(settings()).ask(question(question=text))
    assert result.refused and not result.available and not result.evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["insufficient", "out_of_scope", "investment_advice"])
async def test_model_refusal_verdict_hides_answer_but_keeps_evidence(monkeypatch, verdict):
    fake_model(monkeypatch, supported(verdict=verdict))
    result = await TranscriptAssistantService(settings()).ask(question())
    assert not result.available and result.answer_ko is None and result.evidence
    assert result.refusal_reason == verdict


@pytest.mark.asyncio
async def test_external_evidence_excludes_future_undated_and_other_tickers(monkeypatch):
    def citation(identifier, ticker="NVDA", published="2026-01-04"):
        return EvidenceCitation(document_id=identifier, ticker=ticker, published_at=published,
            source_type=EvidenceSourceType.NEWS, source="news", snippet="Demand grew.",
            relevance_score=.8, confidence_score=.8, reliability_score=.8)
    class Retrieval:
        def retrieve(self, request):
            assert request.metadata["as_of"].startswith("2026-01-05T12:")
            return SimpleNamespace(evidence=[citation("safe"), citation("future", published="2026-01-06"),
                citation("unknown", published=None), citation("other", ticker="AAPL"),
                citation("same_day_unknown_time", published="2026-01-05"),
                citation("same_day_timestamp", published="2026-01-05").model_copy(update={
                    "metadata": {"published_at_epoch": datetime(2026, 1, 5, 10, tzinfo=UTC).timestamp()}})])
    fake_model(monkeypatch, supported())
    result = await TranscriptAssistantService(settings(), Retrieval()).ask(question())
    assert result.available
    assert [item.document_id for item in result.evidence] == ["call-1:81", "safe", "same_day_timestamp"]


def test_contract_validates_segment_pair_and_timezone_and_glossary():
    app = FastAPI()
    app.include_router(router)
    app.state.settings = settings(gemini_api_key="")
    client = TestClient(app)
    glossary = client.get("/v1/engine/glossary").json()
    assert len(glossary["terms"]) == 41 and glossary["version"]
    assert all(item.definition_ko and item.why_ko for item in get_glossary().terms)
    payload = question().model_dump(mode="json")
    payload["segment_sequences"] = [0, 1]
    assert client.post("/v1/engine/transcript/ask", json=payload).status_code == 422


@pytest.mark.asyncio
async def test_verifier_rejects_answer_even_when_quote_is_real(monkeypatch):
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs["prompt"])
        output = supported(answer_ko="내년 매출은 두 배가 됩니다.") if len(calls) == 1 else {
            "verdict": "insufficient", "answer_ko": "", "citations": []}
        return GenerationUsage(text=json.dumps(output))
    monkeypatch.setattr("services.transcript_assistant_service.gemini_client.generate_content_with_metadata", generate)
    result = await TranscriptAssistantService(settings()).ask(question())
    assert len(calls) == 2 and not result.available and result.answer_ko is None
    assert result.refusal_reason == "insufficient" and result.evidence


@pytest.mark.asyncio
async def test_insufficient_evidence_question_does_not_invent_missing_reason(monkeypatch):
    async def fail(**kwargs):
        raise AssertionError("No reason was supplied to explain")
    monkeypatch.setattr("services.transcript_assistant_service.gemini_client.generate_content_with_metadata", fail)
    result = await TranscriptAssistantService(settings()).ask(question(question="왜 근거 부족인가요?"))
    assert not result.available and result.refusal_reason == "insufficient"
    assert result.evidence and result.warnings == ["insufficient_reason_not_provided"]


@pytest.mark.asyncio
async def test_insufficient_evidence_answer_must_cite_actual_reason(monkeypatch):
    request = question(question="왜 근거 부족인가요?", insufficient_reason="No prior call was available.")
    fake_model(monkeypatch, supported(answer_ko="직전 콜이 없어서 비교 근거가 부족합니다.",
        citations=[{"evidence_index": 1, "quote": "No prior call was available."}]))
    result = await TranscriptAssistantService(settings()).ask(request)
    assert result.available and result.evidence[1].source == "analysis_insufficient_reason"
    fake_model(monkeypatch, supported())
    assert not (await TranscriptAssistantService(settings()).ask(request)).available


@pytest.mark.asyncio
async def test_comp_sales_term_translation_is_consistent(monkeypatch):
    request = TranscriptTranslateRequest(ticker="WMT", call_id="w", sequence=0, text="Comp sales grew 5%.")
    service = TranscriptAssistantService(settings())
    fake_model(monkeypatch, {"text_ko": "전체 매출은 5% 성장했습니다.", "meaning_preserved": True})
    rejected = await service.translate(request)
    assert not rejected.available and "translation_glossary_mismatch:comparable sales" in rejected.warnings
    fake_model(monkeypatch, {"text_ko": "기존점 매출은 5% 성장했습니다.", "meaning_preserved": True})
    assert (await service.translate(request)).available


def test_live_routes_translate_and_answer_return_valid_contracts(monkeypatch):
    from api.routers.transcript_translation import router as translation_router
    from services.transcript_translation_service import TranscriptTranslationService
    app = FastAPI()
    app.include_router(router)
    app.include_router(translation_router)
    app.state.settings = settings()
    app.state.transcript_translation_service = TranscriptTranslationService(settings=settings(gemini_primary_thinking_level="minimal"))
    client = TestClient(app)
    fake_model(monkeypatch, {"text_ko": "매출은 20% 성장했습니다.", "meaning_preserved": True})
    translation = client.post("/v1/engine/transcript/translate", json={
        "ticker": "NVDA", "call_id": "call-1", "sequence": 81, "text": "Revenue grew 20%."})
    assert translation.status_code == 200 and translation.json()["text_ko"] == "매출은 20% 성장했습니다."
    fake_model(monkeypatch, supported())
    response = client.post("/v1/engine/transcript/ask", json=question().model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["available"]
    assert response.json()["segment_sequences"] == [81]
    assert response.json()["citations"][0]["quote"] in response.json()["evidence"][0]["snippet"]
    payload = question().model_dump(mode="json")
    payload["as_of"] = "2026-01-05T12:00:00"
    assert client.post("/v1/engine/transcript/ask", json=payload).status_code == 422


def test_glossary_longest_nonoverlapping_matches():
    from services.transcript_glossary import matching_terms
    assert {t.term for t in matching_terms('non-GAAP diluted EPS')} == {'non-GAAP', 'diluted EPS'}
    assert {t.term for t in matching_terms('GAAP and non-GAAP')} == {'GAAP', 'non-GAAP'}


@pytest.mark.asyncio
async def test_non_gaap_translation_does_not_require_gaap_expansion(monkeypatch):
    fake_model(monkeypatch, {'text_ko': '조정 기준 희석주당순이익은 5입니다.', 'meaning_preserved': True})
    result = await TranscriptAssistantService(settings()).translate(TranscriptTranslateRequest(
        ticker='NVDA', call_id='call-1', sequence=0, text='Non-GAAP diluted EPS was 5.'))
    assert result.available


@pytest.mark.asyncio
async def test_explicit_other_ticker_refused_without_model(monkeypatch):
    calls = fake_model(monkeypatch, supported())
    result = await TranscriptAssistantService(settings()).ask(question(question='$AAPL 매출은 왜 늘었나요?'))
    assert result.refused and result.refusal_reason == 'out_of_scope' and not calls


@pytest.mark.asyncio
async def test_prior_call_missing_does_not_invent_comparison(monkeypatch):
    calls = fake_model(monkeypatch, supported())
    result = await TranscriptAssistantService(settings()).ask(question(question='직전 콜과 비교해 주세요'))
    assert result.refusal_reason == 'insufficient' and result.warnings == ['prior_transcript_unavailable']
    assert len(result.evidence) == 1 and not calls


class PriorRepository:
    def __init__(self, current=False, bad_chunk=False):
        self.current, self.bad_chunk, self.before = current, bad_chunk, []

    def find_latest_transcript(self, *, ticker, before):
        self.before.append(before)
        current = self.current and len(self.before) == 1
        return {'ticker': ticker, 'document_id': 'call-1' if current else 'prior',
                'published_at_epoch': datetime(2026, 1, 4 if current else 3, tzinfo=UTC).timestamp()}

    def search_prior_transcript_chunks(self, **kwargs):
        return [EvidenceCitation(document_id='wrong' if self.bad_chunk else 'prior', ticker='NVDA',
                source_type=EvidenceSourceType.EARNINGS_CALL, source='prior_transcript',
                published_at='2026-01-03T00:00:00+00:00', snippet='Revenue increased 10%.',
                relevance_score=.8, reliability_score=.8, confidence_score=.8)]


@pytest.mark.asyncio
async def test_prior_comparison_requires_both_current_and_prior_quotes(monkeypatch):
    repo = PriorRepository(current=True)
    answer = supported(citations=[{'evidence_index': 0, 'quote': 'Revenue increased 20%'},
                                 {'evidence_index': 1, 'quote': 'Revenue increased 10%.'}],
                       answer_ko='매출 증가율은 직전 10%에서 20%로 올랐습니다.')
    fake_model(monkeypatch, answer)
    result = await TranscriptAssistantService(settings(), transcript_repository=repo).ask(
        question(question='직전 콜과 비교해 주세요'))
    assert result.available and len(repo.before) == 2 and repo.before[1] < repo.before[0]
    fake_model(monkeypatch, supported())
    rejected = await TranscriptAssistantService(settings(), transcript_repository=repo).ask(
        question(question='직전 콜과 비교해 주세요'))
    assert not rejected.available and rejected.refusal_reason == 'invalid_or_unsupported_response'


@pytest.mark.asyncio
async def test_prior_wrong_document_excluded(monkeypatch):
    calls = fake_model(monkeypatch, supported())
    result = await TranscriptAssistantService(settings(), transcript_repository=PriorRepository(bad_chunk=True)).ask(
        question(question='직전 콜과 비교해 주세요'))
    assert result.refusal_reason == 'insufficient' and not calls


@pytest.mark.asyncio
async def test_glossary_definition_is_citable_and_required(monkeypatch):
    term = next(t for t in get_glossary().terms if t.term == 'comparable sales')
    value = supported(answer_ko=term.definition_ko, citations=[
        {'evidence_index': 0, 'quote': 'Comp sales'}, {'evidence_index': 1, 'quote': term.definition_ko}])
    fake_model(monkeypatch, value)
    request = question(segment_texts=['Comp sales grew 5%.'], question='comp sales 뜻이 무엇인가요?')
    result = await TranscriptAssistantService(settings()).ask(request)
    assert result.available and result.evidence[1].source == 'curated_glossary'
    value['citations'] = value['citations'][:1]
    fake_model(monkeypatch, value)
    result = await TranscriptAssistantService(settings()).ask(request)
    assert not result.available
