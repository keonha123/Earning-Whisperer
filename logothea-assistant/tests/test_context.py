import pytest

from assistant.context import (
    PRIOR_CALL_GAP_SECONDS,
    BaseSources,
    ContextAssembler,
    ContextError,
)
from assistant.schemas import AskRequest
from tests.fakes import NOT_FOUND, FakeBackend, FakeEngine, segments_payload

AS_OF = 1787227218


def _request(**overrides):
    data = {"user_id": "u1", "ticker": "WMT", "call_id": "c1", "as_of_sequence": 3,
            "as_of_epoch": AS_OF, "question": "q"}
    data.update(overrides)
    return AskRequest(**data)


def _assembler(backend=None, engine=None, timeout=0.2):
    return ContextAssembler(backend or FakeBackend(), engine or FakeEngine(),
                            timeout_seconds=timeout, news_top_k=6, news_lookback_days=30)


def _base(segments=None, estimates=None, prior=None, missing=None):
    return BaseSources(segments=segments or segments_payload([1, 2, 3]), estimates=estimates,
                       prior=prior, missing_sources=missing or [])


async def test_gather_base_passes_time_bounds():
    backend, engine = FakeBackend(), FakeEngine()
    await _assembler(backend, engine).gather_base(_request())

    assert ("segments", {"call_id": "c1", "until_sequence": 3}) in backend.calls
    assert ("estimates", {"ticker": "WMT", "as_of_epoch": AS_OF}) in backend.calls
    assert engine.calls == [("prior_call_statements", {"ticker": "WMT", "before_epoch": AS_OF - PRIOR_CALL_GAP_SECONDS})]


async def test_segments_not_found_and_unavailable_are_errors():
    with pytest.raises(ContextError) as error:
        await _assembler(FakeBackend(segments=NOT_FOUND)).gather_base(_request())
    assert error.value.code == "segments_not_found"

    with pytest.raises(ContextError) as error:
        await _assembler(FakeBackend(fail={"segments"})).gather_base(_request())
    assert error.value.code == "context_unavailable"

    with pytest.raises(ContextError) as error:
        await _assembler(FakeBackend(delays={"segments": 0.5}), timeout=0.05).gather_base(_request())
    assert error.value.code == "context_unavailable"


async def test_slow_or_failed_side_sources_are_dropped_and_reported():
    backend = FakeBackend(fail={"estimates"})
    engine = FakeEngine(delays={"prior_call_statements": 0.5})
    base = await _assembler(backend, engine, timeout=0.05).gather_base(_request())

    assert base.estimates is None
    assert base.prior is None
    assert base.missing_sources == ["estimates", "prior_call"]


async def test_prior_lookup_warning_counts_as_missing_but_not_found_does_not():
    failed = FakeEngine(prior={"available": False, "statements": [], "warnings": ["prior_call_lookup_failed"]})
    assert (await _assembler(engine=failed).gather_base(_request())).missing_sources == ["prior_call"]

    not_found = FakeEngine()
    assert (await _assembler(engine=not_found).gather_base(_request())).missing_sources == []


async def test_gather_news_uses_query_and_reports_failures():
    engine = FakeEngine(news={"hits": [{"doc_id": "d1"}], "warnings": []})
    hits, missing = await _assembler(engine=engine).gather_news(_request(), "guidance outlook")
    assert hits == [{"doc_id": "d1"}] and missing == []
    assert engine.calls[0] == ("news_search", {"ticker": "WMT", "query": "guidance outlook", "as_of_epoch": AS_OF,
                                               "lookback_days": 30, "top_k": 6})

    empty = FakeEngine()
    assert await _assembler(engine=empty).gather_news(_request(), "  ") == ([], [])
    assert empty.calls == []

    assert await _assembler(engine=FakeEngine(fail={"news_search"})).gather_news(_request(), "q") == ([], ["news"])
    warned = FakeEngine(news={"hits": [], "warnings": ["news_search_failed"]})
    assert await _assembler(engine=warned).gather_news(_request(), "q") == ([], ["news"])


def test_build_drops_segments_after_as_of_and_marks_by_sequence():
    payload = segments_payload([1, 2, 3, 4, 5])
    payload["segments"].append(dict(payload["segments"][1]))  # sequence 2 중복
    bundle = _assembler().build(_request(as_of_sequence=3), _base(segments=payload), [], [])

    assert [e.marker for e in bundle.segments] == ["S1", "S2", "S3"]
    assert bundle.segments[0].type == "segment"
    assert bundle.segments[0].ref == "1"
    assert bundle.segments[0].speaker == "John Furner"
    assert bundle.segments[0].start_ms == 6000
    assert bundle.as_of_sequence == 3


def test_build_reports_gaps_and_uses_last_present_sequence():
    bundle = _assembler().build(_request(as_of_sequence=9), _base(segments=segments_payload([1, 2, 5])), [], [])
    assert bundle.as_of_sequence == 5
    assert "segments_incomplete" in bundle.missing_sources


def test_build_raises_when_no_segment_is_within_as_of():
    with pytest.raises(ContextError) as error:
        _assembler().build(_request(as_of_sequence=3), _base(segments=segments_payload([7, 8])), [], [])
    assert error.value.code == "segments_not_found"


def test_build_keeps_anchor_only_if_present():
    assert _assembler().build(_request(anchor_sequence=2), _base(), [], []).anchor_sequence == 2
    gappy = _base(segments=segments_payload([1, 3]))
    assert _assembler().build(_request(anchor_sequence=2), gappy, [], []).anchor_sequence is None


def test_build_drops_news_after_as_of_and_numbers_contiguously():
    hits = [
        {"doc_id": "a", "title": "Walmart raises outlook", "source": "Reuters", "published_at": AS_OF - 3600, "snippet": "s1"},
        {"doc_id": "b", "title": "Future", "source": "X", "published_at": AS_OF + 1, "snippet": "s2"},
        {"doc_id": "c", "title": "No date", "source": "X", "published_at": 0, "snippet": "s3"},
        {"doc_id": "d", "title": "Older", "source": "AP", "published_at": AS_OF - 86400, "snippet": "s4"},
    ]
    bundle = _assembler().build(_request(), _base(), hits, ["news"])

    assert [(e.marker, e.ref) for e in bundle.news] == [("N1", "a"), ("N2", "d")]
    assert bundle.news[0].text == "Walmart raises outlook\ns1"
    assert bundle.news[0].source == "Reuters"
    assert bundle.news[0].published_at == AS_OF - 3600
    assert bundle.missing_sources == ["news"]


def test_build_prior_statements_in_order():
    prior = {"available": True, "fiscal_quarter": "Q1 FY2027", "published_at_epoch": 1779000000,
             "statements": [{"statement_id": "s2", "order": 2, "speaker": "B", "text": "second"},
                            {"statement_id": "s1", "order": 1, "speaker": "A", "text": "first"}]}
    bundle = _assembler().build(_request(), _base(prior=prior), [], [])
    assert [(e.marker, e.ref, e.text) for e in bundle.prior] == [("P1", "s1", "first"), ("P2", "s2", "second")]
    assert bundle.prior[0].title == "Q1 FY2027"
    assert bundle.prior[0].type == "prior_statement"


def test_build_estimates_labels_this_call_and_formats_numbers():
    estimates = {
        "ticker": "WMT", "as_of_epoch": AS_OF,
        "upcoming": {"scheduled_at": "2026-08-20T11:00:00Z", "eps_estimate": 0.74, "revenue_estimate": 176000000000.0},
        "recent_results": [{"announced_at": "2026-05-15T11:00:00Z", "fiscal_period_label": "Q1 FY27", "eps_estimate": 0.6,
                            "eps_actual": 0.61, "surprise_percent": 1.67, "price_reaction_percent": None}],
    }
    bundle = _assembler().build(_request(), _base(estimates=estimates), [], [])

    assert [e.marker for e in bundle.estimates] == ["E1", "E2"]
    assert bundle.estimates[0].text == (
        "이번 실적 발표 시장 예상(예정 2026-08-20): EPS 추정 $0.74, 매출 추정 $176.00 billion")
    assert bundle.estimates[1].text == (
        "Q1 FY27 실적(발표 2026-05-15): EPS 추정 $0.60, 실제 $0.61, 서프라이즈 1.67%, 발표 후 7일 주가 반응 자료 없음")


def test_build_estimates_labels_far_schedule_as_next():
    estimates = {"upcoming": {"scheduled_at": "2026-11-19T11:00:00Z", "eps_estimate": None, "revenue_estimate": None},
                 "recent_results": []}
    bundle = _assembler().build(_request(), _base(estimates=estimates), [], [])
    assert bundle.estimates[0].text == "다음 실적 발표 시장 예상(예정 2026-11-19): EPS 추정 자료 없음, 매출 추정 자료 없음"


def test_evidence_index_covers_all_markers():
    bundle = _assembler().build(_request(), _base(), [], [])
    assert list(bundle.evidence) == ["S1", "S2", "S3"]
