from contextlib import aclosing

from assistant.classifier import Classification, GlossaryProvider
from assistant.context import ContextAssembler
from assistant.llm import LLMError
from assistant.pipeline import AnswerPipeline
from assistant.prompts import REFUSAL_TEXTS
from assistant.schemas import AskRequest
from tests.fakes import NOT_FOUND, FakeBackend, FakeEngine, FakeLLM, segments_payload

AS_OF = 1787227218
_GLOSSARY = {"version": 1, "terms": [{"term": "comp sales", "aliases": [], "ko": "기존점 매출", "category": "retail",
                                      "definition_ko": "1년 이상 운영된 점포 매출 증가율입니다."}]}


def _request(**overrides):
    data = {"user_id": "u1", "ticker": "WMT", "call_id": "c1", "as_of_sequence": 3, "as_of_epoch": AS_OF,
            "question": "기존점 매출이 얼마나 늘었어?"}
    data.update(overrides)
    return AskRequest(**data)


def _answer(query="comp sales growth", category="answer", term=None):
    return Classification(category=category, glossary_term=term, search_query=query)


def _segments():
    payload = segments_payload([1, 2, 3])
    payload["segments"][2]["text"] = "Comp sales grew 4.5%."
    return payload


def _pipeline(llm, backend=None, engine=None, clock=None):
    backend = backend or FakeBackend(segments=_segments(), glossary=_GLOSSARY)
    assembler = ContextAssembler(backend, engine or FakeEngine(), timeout_seconds=0.2, news_top_k=6,
                                 news_lookback_days=30)
    ticks = iter([100.0, 101.25])
    return AnswerPipeline(llm=llm, assembler=assembler, glossary=GlossaryProvider(backend.glossary),
                          clock=clock or (lambda: next(ticks)))


async def _collect(pipeline, request):
    return [event async for event in pipeline.run(request)]


async def test_answer_flow_emits_meta_deltas_citations_done():
    llm = FakeLLM(parsed=_answer(), deltas=["기존점 매출은 ", "4.5% 늘었습니다 [S3]."])
    events = await _collect(_pipeline(llm), _request())

    assert [name for name, _ in events] == ["meta", "delta", "delta", "citations", "done"]
    assert events[0][1] == {"scope": "call", "as_of_sequence": 3, "as_of_time": "2026-08-20T12:00:18Z",
                            "anchor_sequence": None, "missing_sources": []}
    assert events[3][1][0]["marker"] == "S3" and events[3][1][0]["verified"] is True
    done = events[4][1]
    assert done["status"] == "answered"
    assert done["refusal_reason"] is None
    assert done["warnings"] == []
    assert done["usage"] == {"input_tokens": 1030, "output_tokens": 60, "cached_tokens": 800}
    assert done["latency_ms"] == 1250
    evidence_message = llm.stream_calls[0][1].text
    assert '<item id="S3"' in evidence_message


async def test_explicit_trade_question_is_refused_without_any_llm_call():
    llm = FakeLLM()
    events = await _collect(_pipeline(llm), _request(question="지금 사야 돼?"))

    assert [name for name, _ in events] == ["meta", "delta", "done"]
    assert events[1][1] == {"text": REFUSAL_TEXTS["investment_advice"]}
    assert events[2][1]["status"] == "refused"
    assert events[2][1]["refusal_reason"] == "investment_advice"
    assert events[2][1]["suggested_question_ids"] == ["guidance", "vs_expectations"]
    assert llm.parse_calls == [] and llm.stream_calls == []


async def test_llm_classified_refusals_skip_generation():
    for category in ("price_prediction", "out_of_scope"):
        llm = FakeLLM(parsed=_answer(category=category))
        events = await _collect(_pipeline(llm), _request(question="다음 주에 주가 오를까?"))
        assert events[-1][1]["status"] == "refused"
        assert events[-1][1]["refusal_reason"] == category
        assert llm.stream_calls == []


async def test_glossary_hit_answers_from_dictionary():
    llm = FakeLLM(parsed=_answer(category="glossary", term="Comp Sales"))
    events = await _collect(_pipeline(llm), _request(question="comp sales 가 뭐야?"))

    assert [name for name, _ in events] == ["meta", "delta", "done"]
    assert events[1][1]["text"].startswith("comp sales(기존점 매출):")
    assert events[2][1]["status"] == "answered"
    assert llm.stream_calls == []


async def test_glossary_miss_falls_back_to_generation():
    llm = FakeLLM(parsed=_answer(category="glossary", term="EBITDA"), deltas=["설명입니다 [S1]."])
    events = await _collect(_pipeline(llm), _request(question="EBITDA 가 뭐야?"))
    assert events[-1][1]["status"] == "answered"
    assert len(llm.stream_calls) == 1


async def test_no_evidence_answer_is_flagged():
    llm = FakeLLM(parsed=_answer(), deltas=["이번 콜과 제공된 자료에서 찾지 못했습니다."])
    events = await _collect(_pipeline(llm), _request())
    assert events[-1][1]["status"] == "no_evidence"


async def test_segments_not_found_is_an_error_before_meta():
    llm = FakeLLM(parsed=_answer())
    events = await _collect(_pipeline(llm, backend=FakeBackend(segments=NOT_FOUND)), _request())
    assert events == [("error", {"code": "segments_not_found", "message": "이 콜의 자막을 찾지 못했습니다."})]
    assert llm.stream_calls == []


async def test_classification_failure_is_an_error():
    llm = FakeLLM(parse_error=LLMError("llm_timeout", "slow"))
    events = await _collect(_pipeline(llm), _request())
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["code"] == "llm_timeout"


async def test_stream_failure_keeps_sent_deltas_then_errors():
    llm = FakeLLM(parsed=_answer(), deltas=["앞부분", "뒷부분"], stream_error=LLMError("llm_failed", "x"), fail_after=1)
    events = await _collect(_pipeline(llm), _request())
    assert [name for name, _ in events] == ["meta", "delta", "error"]
    assert events[1][1] == {"text": "앞부분"}
    assert events[2][1]["code"] == "llm_failed"


async def test_closing_the_consumer_closes_the_llm_stream():
    llm = FakeLLM(parsed=_answer(), deltas=["하나", "둘", "셋"])
    async with aclosing(_pipeline(llm).run(_request())) as events:
        async for name, _ in events:
            if name == "delta":
                break
    assert llm.stream_closed is True


async def test_missing_sources_and_anchor_reach_meta_and_prompt():
    llm = FakeLLM(parsed=_answer(), deltas=["답 [S2]."])
    engine = FakeEngine(fail={"news_search"})
    events = await _collect(_pipeline(llm, engine=engine), _request(anchor_sequence=2))

    meta = events[0][1]
    assert meta["scope"] == "anchor" and meta["anchor_sequence"] == 2
    assert meta["missing_sources"] == ["news"]
    assert "관련 뉴스" in llm.stream_calls[0][-1].text


async def test_suggested_question_uses_preset_query_without_classification_call():
    llm = FakeLLM(deltas=["요약입니다 [S1]."])
    engine = FakeEngine()
    await _collect(_pipeline(llm, engine=engine), _request(question="지금까지 핵심을 요약해 줘", suggested_question_id="summary"))
    assert llm.parse_calls == []
    assert engine.calls[-1][1]["query"] == "earnings call key highlights results"
