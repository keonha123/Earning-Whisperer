import json

from assistant.context import Evidence
from assistant.llm import ToolCall
from assistant.tools import MAX_READ_SEGMENTS, MAX_TOOL_CALLS, TOOL_SPECS, AgentToolbox


def _seg(seq, text=None):
    return Evidence(marker=f"S{seq}", type="segment", ref=str(seq), text=text or f"segment {seq} text",
                    speaker="CEO", start_ms=seq * 5000)


SEGMENTS = [_seg(0, "Welcome."), _seg(1, "Comp sales grew 4.5%."), _seg(2, "Tariff refunds helped margin."),
            *[_seg(i) for i in range(3, 60)]]
PRIOR = [Evidence(marker="P1", type="prior_statement", ref="p1", text="Last quarter comp sales grew 4.1%.",
                  title="Q1 FY27", speaker="CFO")]
ESTIMATES = [Evidence(marker="E1", type="estimate", ref="upcoming", text="EPS 추정 $0.74", title="이번 실적 발표 시장 예상")]


def _call(name, args, call_id="c1"):
    return ToolCall(call_id=call_id, name=name, arguments=json.dumps(args))


def _box(news=None, news_missing=()):
    queries = []

    async def news_search(query):
        queries.append(query)
        return (news or []), list(news_missing)

    box = AgentToolbox(segments=SEGMENTS, prior=PRIOR, estimates=ESTIMATES, anchor_sequence=None,
                       news_search=news_search, as_of_epoch=1787227300)
    return box, queries


def test_tool_specs_are_strict_schemas():
    assert [spec.name for spec in TOOL_SPECS] == ["search_call", "read_call", "search_news", "get_prior_call",
                                                  "get_estimates"]
    for spec in TOOL_SPECS:
        assert spec.parameters["additionalProperties"] is False
        assert set(spec.parameters["required"]) == set(spec.parameters["properties"])


async def test_search_call_returns_matching_segments_and_registers_them():
    box, _ = _box()
    result = await box.call(_call("search_call", {"query": "comp sales"}))
    assert result.call_id == "c1"
    assert '<item id="S1"' in result.output and "Comp sales grew 4.5%." in result.output
    assert "S1" in box.evidence
    assert box.call_names == ["search_call"]


async def test_search_call_without_hits_says_so():
    box, _ = _box()
    result = await box.call(_call("search_call", {"query": "zzz"}))
    assert "찾지 못했습니다" in result.output


async def test_read_call_clips_to_known_segments_and_limit():
    box, _ = _box()
    result = await box.call(_call("read_call", {"start_sequence": 0, "end_sequence": 999}))
    assert result.output.count("<item ") == MAX_READ_SEGMENTS
    assert f'id="S{MAX_READ_SEGMENTS}"' not in result.output
    assert "이어서 읽으려면" in result.output


async def test_read_call_never_returns_segments_outside_the_given_list():
    box, _ = _box()
    result = await box.call(_call("read_call", {"start_sequence": 58, "end_sequence": 70}))
    assert 'id="S59"' in result.output and 'id="S60"' not in result.output


async def test_search_news_numbers_continue_and_repeat_articles_keep_their_marker():
    hits = [{"doc_id": "d1", "title": "WMT beats", "snippet": "EPS 0.81", "source": "Reuters", "published_at": 1787227200},
            {"doc_id": "d2", "title": "Late", "snippet": "after", "source": "X", "published_at": 1787229999}]
    box, queries = _box(news=hits)
    first = await box.call(_call("search_news", {"query": "walmart earnings"}))
    second = await box.call(_call("search_news", {"query": "walmart eps"}, call_id="c2"))
    assert queries == ["walmart earnings", "walmart eps"]
    assert 'id="N1"' in first.output and 'id="N1"' in second.output
    assert "Late" not in first.output  # 질문 시점 이후 기사는 뺀다
    assert set(k for k in box.evidence if k.startswith("N")) == {"N1"}


async def test_search_news_failure_is_reported_and_recorded():
    box, _ = _box(news=[], news_missing=["news"])
    result = await box.call(_call("search_news", {"query": "walmart"}))
    assert "불러오지 못했습니다" in result.output
    assert box.missing_sources == ["news"]


async def test_prior_and_estimates_render_preloaded_items():
    box, _ = _box()
    prior = await box.call(_call("get_prior_call", {}))
    estimates = await box.call(_call("get_estimates", {}, call_id="c2"))
    assert 'id="P1"' in prior.output and 'id="E1"' in estimates.output
    assert {"P1", "E1"} <= set(box.evidence)


async def test_bad_arguments_unknown_tool_and_call_limit_are_reported_not_raised():
    box, _ = _box()
    bad = await box.call(ToolCall(call_id="c1", name="search_call", arguments="{not json"))
    not_object = [await box.call(ToolCall(call_id="c2", name="search_call", arguments=raw)) for raw in ("[]", "null")]
    unknown = await box.call(_call("delete_everything", {}))
    assert "인자를 읽지 못했습니다" in bad.output
    assert all("인자를 읽지 못했습니다" in r.output for r in not_object)
    assert "없는 도구" in unknown.output
    for index in range(MAX_TOOL_CALLS):
        await box.call(_call("get_estimates", {}, call_id=f"x{index}"))
    over = await box.call(_call("get_estimates", {}, call_id="last"))
    assert "도구 호출 한도" in over.output


def test_preload_registers_and_renders_items():
    box, _ = _box()
    text = box.preload(SEGMENTS[1:3])
    assert text.startswith("<evidence>") and 'id="S2"' in text
    assert {"S1", "S2"} <= set(box.evidence)
