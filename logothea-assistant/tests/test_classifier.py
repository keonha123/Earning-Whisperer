import pytest

from assistant.classifier import (
    SUGGESTED_SEARCH_QUERIES,
    Classification,
    Glossary,
    GlossaryProvider,
    classify,
    glossary_answer,
)
from assistant.llm import Usage
from assistant.schemas import AskRequest
from tests.fakes import FakeLLM


def _request(**overrides):
    data = {"user_id": "u1", "ticker": "WMT", "call_id": "c1", "as_of_sequence": 10,
            "as_of_epoch": 1787227218, "question": "그 숫자는 지난 분기보다 좋아진 거야?"}
    data.update(overrides)
    return AskRequest(**data)


_GLOSSARY = {
    "version": 2,
    "terms": [
        {"term": "comp sales", "aliases": ["comparable sales", "Comps"], "ko": "기존점 매출", "category": "retail",
         "definition_ko": "1년 이상 운영된 점포만 집계한 매출 증가율입니다.", "why_ko": "신규 출점 효과를 뺀 실제 영업력을 보여줍니다."},
        {"term": "eCommerce", "aliases": [], "ko": "이커머스", "category": "retail"},
    ],
}


async def test_suggested_question_skips_the_llm():
    llm = FakeLLM()
    classification, usage = await classify(llm, _request(question="가이던스가 바뀌었어?", suggested_question_id="guidance"))
    assert classification == Classification(category="answer", glossary_term=None,
                                            search_query=SUGGESTED_SEARCH_QUERIES["guidance"])
    assert usage == Usage()
    assert llm.parse_calls == []


def test_every_suggested_question_has_a_search_query():
    assert set(SUGGESTED_SEARCH_QUERIES) == {"summary", "vs_last_quarter", "guidance", "vs_expectations", "risks"}


async def test_explicit_trade_request_is_refused_without_the_llm():
    llm = FakeLLM()
    classification, _ = await classify(llm, _request(question="지금 사야 돼?"))
    assert classification.category == "investment_advice"
    assert llm.parse_calls == []


async def test_other_questions_use_the_llm_with_history():
    expected = Classification(category="answer", glossary_term=None, search_query="WMT comp sales versus prior quarter")
    llm = FakeLLM(parsed=expected)
    request = _request(history=[{"role": "user", "text": "기존점 매출이 얼마야?"},
                                {"role": "assistant", "text": "4.5% 입니다 [S3]"}])

    classification, usage = await classify(llm, request)

    assert classification == expected
    assert usage == Usage(30, 10, 0)
    messages = llm.parse_calls[0]
    assert messages[0].role == "system" and "WMT" in messages[0].text
    assert [(m.role, m.text) for m in messages[1:]] == [
        ("user", "기존점 매출이 얼마야?"), ("assistant", "4.5% 입니다 [S3]"), ("user", request.question)]


def test_glossary_lookup_matches_term_and_aliases_case_insensitively():
    glossary = Glossary(_GLOSSARY)
    assert glossary.lookup("Comp Sales")["ko"] == "기존점 매출"
    assert glossary.lookup(" comps ")["ko"] == "기존점 매출"
    assert glossary.lookup("comparable  sales")["ko"] == "기존점 매출"


def test_glossary_lookup_ignores_terms_without_definition_and_unknown_terms():
    glossary = Glossary(_GLOSSARY)
    assert glossary.lookup("eCommerce") is None
    assert glossary.lookup("EBITDA") is None
    assert glossary.lookup(None) is None


def test_glossary_answer_text():
    entry = Glossary(_GLOSSARY).lookup("comp sales")
    assert glossary_answer(entry) == (
        "comp sales(기존점 매출): 1년 이상 운영된 점포만 집계한 매출 증가율입니다. 신규 출점 효과를 뺀 실제 영업력을 보여줍니다.")


async def test_glossary_provider_loads_once():
    calls = []

    async def loader():
        calls.append(1)
        return _GLOSSARY

    provider = GlossaryProvider(loader)
    first = await provider.get()
    second = await provider.get()
    assert first is second and first is not None
    assert len(calls) == 1


async def test_glossary_provider_returns_none_on_failure_and_retries_later():
    attempts = []

    async def loader():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("backend down")
        return _GLOSSARY

    provider = GlossaryProvider(loader)
    assert await provider.get() is None
    assert await provider.get() is not None
    assert len(attempts) == 2
