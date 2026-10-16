import json

import pytest

from assistant.agent import MAX_TOOL_ROUNDS, AgentAnswerer, AgentFinished
from assistant.context import BaseSources, ContextAssembler, ContextError
from assistant.llm import LLMError, RoundDone, TextDelta, ToolCall, Usage
from assistant.schemas import AskRequest
from tests.fakes import FakeBackend, FakeEngine, FakeLLM, segments_payload

AS_OF = 1787227218


def _request(**overrides):
    data = {"user_id": "u1", "ticker": "WMT", "call_id": "c1", "as_of_sequence": 3, "as_of_epoch": AS_OF,
            "question": "기존점 매출이 얼마나 늘었어?"}
    data.update(overrides)
    return AskRequest(**data)


def _base(sequences=(1, 2, 3)):
    payload = segments_payload(list(sequences))
    payload["segments"][-1]["text"] = "Comp sales grew 4.5%."
    return BaseSources(segments=payload, estimates=None, prior=None, missing_sources=[])


def _answerer(llm, engine=None):
    assembler = ContextAssembler(FakeBackend(), engine or FakeEngine(), timeout_seconds=0.2, news_top_k=6,
                                 news_lookback_days=30)
    return AgentAnswerer(llm, assembler)


def _tool_round(*calls):
    return [RoundDone(usage=Usage(100, 10, 0), tool_calls=list(calls),
                      items=[{"type": "function_call", "call_id": c.call_id, "name": c.name, "arguments": c.arguments}
                             for c in calls])]


def _answer_round(*texts):
    return [*(TextDelta(t) for t in texts), RoundDone(usage=Usage(200, 20, 0), tool_calls=[], items=[])]


async def _collect(answerer, request, base=None, category="answer", usage=None):
    return [e async for e in answerer.run(request, base or _base(), category, usage or Usage())]


async def test_tool_round_then_answer_streams_meta_deltas_and_finishes_with_tool_evidence():
    search = ToolCall(call_id="c1", name="search_call", arguments=json.dumps({"query": "comp sales"}))
    llm = FakeLLM(rounds=[_tool_round(search), _answer_round("4.5% 늘었습니다 ", "[S3].")])
    usage = Usage()

    events = await _collect(_answerer(llm), _request(), usage=usage)

    names = [e[0] if isinstance(e, tuple) else "finished" for e in events]
    assert names == ["meta", "delta", "delta", "finished"]
    assert events[0][1]["as_of_sequence"] == 3 and events[0][1]["scope"] == "call"
    finished = events[-1]
    assert isinstance(finished, AgentFinished)
    assert finished.answer == "4.5% 늘었습니다 [S3]."
    assert "S3" in finished.evidence and finished.warnings == []
    assert usage == Usage(300, 30, 0)
    second_items, _, allow = llm.round_calls[1]
    assert allow is True
    assert second_items[-1].call_id == "c1" and "Comp sales grew 4.5%." in second_items[-1].output


async def test_round_limit_forces_an_answer_without_tools_and_warns():
    loop = ToolCall(call_id="c", name="get_estimates", arguments="{}")
    llm = FakeLLM(rounds=[*[_tool_round(loop) for _ in range(MAX_TOOL_ROUNDS)], _answer_round("자료가 부족합니다.")])

    events = await _collect(_answerer(llm), _request())

    assert [allow for _, _, allow in llm.round_calls] == [True] * MAX_TOOL_ROUNDS + [False]
    assert events[-1].warnings == ["agent_round_limit"]


async def test_anchor_question_preloads_neighbors_and_marks_anchor():
    llm = FakeLLM(rounds=[_answer_round("답 [S2].")])
    base = _base(sequences=(0, 1, 2, 3))
    events = await _collect(_answerer(llm), _request(anchor_sequence=2), base=base)

    first_input = llm.round_calls[0][0]
    user_text = first_input[-1].text
    assert 'id="S2"' in user_text and 'anchor="true"' in user_text and 'id="S0"' in user_text
    assert events[0][1]["scope"] == "anchor" and events[0][1]["anchor_sequence"] == 2
    assert "S2" in events[-1].evidence


async def test_meta_is_sent_even_when_the_answer_is_empty():
    llm = FakeLLM(rounds=[[RoundDone(usage=Usage(), tool_calls=[], items=[])]])
    events = await _collect(_answerer(llm), _request())
    assert events[0][0] == "meta" and isinstance(events[-1], AgentFinished) and events[-1].answer == ""


async def test_missing_segments_is_a_context_error():
    llm = FakeLLM(rounds=[])
    with pytest.raises(ContextError):
        await _collect(_answerer(llm), _request(), base=BaseSources(segments={"segments": []}, estimates=None,
                                                                      prior=None, missing_sources=[]))


async def test_llm_failure_propagates_and_closes_the_round():
    llm = FakeLLM(round_error=LLMError("llm_timeout", "slow"))
    with pytest.raises(LLMError):
        await _collect(_answerer(llm), _request())
    assert llm.round_closed is True


async def test_news_failure_from_a_tool_reaches_meta_missing_sources():
    news = ToolCall(call_id="n", name="search_news", arguments=json.dumps({"query": "walmart"}))
    llm = FakeLLM(rounds=[_tool_round(news), _answer_round("답.")])
    events = await _collect(_answerer(llm, engine=FakeEngine(fail={"news_search"})), _request())
    assert events[0][1]["missing_sources"] == ["news"]
