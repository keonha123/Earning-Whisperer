import pytest

from eval.dataset import EvalItem
from eval.metrics import cost_usd, evidence_recall, percentile, summarize, time_violations
from eval.runner import ItemResult
from eval.transcript import EvalSegment

SEGMENTS = [EvalSegment(i, i * 5000, i * 5000 + 4500, "CEO · A", f"t{i}", 1787227200 + i * 5, i == 9) for i in range(10)]


def item(id, group="answerable", status="answered", as_of=5, gold=(3,), reason=None):
    return EvalItem(id=id, group=group, question="q", as_of_sequence=as_of, expected_status=status,
                    expected_refusal_reason=reason, key_points=["a", "b"] if status == "answered" else [],
                    gold_sequences=list(gold) if status == "answered" else [])


def result(id, status="answered", citations=(), error=None, first=100, total=1000, usage=None):
    return ItemResult(item_id=id, status=status, citations=list(citations), error=error, first_token_ms=first,
                      total_ms=total, usage=usage or {"input_tokens": 1_000_000, "output_tokens": 100_000, "cached_tokens": 0})


def seg(seq, verified=True):
    return {"marker": f"S{seq}", "type": "segment", "ref": str(seq), "verified": verified, "published_at": None}


def test_percentile():
    assert percentile([], 0.5) is None
    assert percentile([100, 200, 300, 400], 0.5) == 250
    assert percentile([100, 200, 300, 400], 0.95) == pytest.approx(385)


def test_cost_uses_model_prices():
    assert cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cached_tokens": 0}, "gpt-6-luna") == pytest.approx(0.60)


def test_time_violations_catch_future_segments_and_news():
    i = item("a", as_of=5)
    r = result("a", citations=[seg(3), seg(7), {"marker": "N1", "type": "news", "ref": "d", "verified": True,
                                                    "published_at": SEGMENTS[5].timestamp + 1}])
    assert time_violations(i, r, SEGMENTS) == ["S7", "N1"]
    assert time_violations(i, result("a", citations=[seg(5)]), SEGMENTS) == []


def test_evidence_recall():
    assert evidence_recall(item("a", gold=(3, 4)), result("a", citations=[seg(3)])) == 0.5
    assert evidence_recall(item("r", status="refused", reason="investment_advice"), result("r", status="refused")) is None


def test_summary_counts_errors_as_wrong_and_separates_refusals():
    items = [
        item("ok"),
        item("err"),
        item("bad-refusal"),
        item("good-refusal", group="refusal", status="refused", reason="investment_advice"),
        item("missed-refusal", group="refusal", status="refused", reason="price_prediction"),
        item("future", as_of=5),
    ]
    results = [
        result("ok", citations=[seg(3)]),
        result("err", status=None, error={"code": "llm_timeout", "message": ""}, first=None),
        result("bad-refusal", status="refused"),
        result("good-refusal", status="refused"),
        result("missed-refusal", status="answered"),
        result("future", citations=[seg(3), seg(8, verified=False)]),
    ]
    summary = summarize(items, results, SEGMENTS)

    assert summary["count"] == 6
    assert summary["errors"] == 1
    assert summary["status_accuracy"] == pytest.approx(3 / 6)
    assert summary["refusals"] == {"appropriate": 1, "inappropriate": 1, "missed": 1}
    assert summary["time_violations"] == {"future": ["S8"]}
    assert summary["assistant_citation_check_rate"] == pytest.approx(2 / 3)
    assert summary["evidence_recall"] == pytest.approx((1 + 0 + 0 + 1) / 4)
    assert summary["by_group"]["refusal"]["status_accuracy"] == 0.5
    assert summary["latency_ms"]["first_token_p50"] == 100
    assert summary["cost_usd"]["total"] == pytest.approx(5 * 0.15 + 0.15)
    assert "judge" not in summary


def test_summary_includes_judge_rates_when_given():
    from eval.judge import CitationVerdict, Judgment, PointVerdict

    items = [item("a"), item("b")]
    results = [result("a"), result("b")]
    judgments = {
        "a": Judgment(points=[PointVerdict(point_index=0, verdict="present"), PointVerdict(point_index=1, verdict="contradicted")],
                      citations=[CitationVerdict(marker="S3", supported=True)]),
        "b": Judgment(points=[PointVerdict(point_index=0, verdict="absent"), PointVerdict(point_index=1, verdict="present")],
                      citations=[CitationVerdict(marker="S3", supported=False)]),
    }
    summary = summarize(items, results, SEGMENTS, judgments)
    assert summary["judge"] == {"judged_items": 2, "key_point_coverage": 0.5, "key_point_contradicted": 0.25,
                                "citation_precision": 0.5}


def test_time_violation_published_at_applies_to_any_citation_once():
    i = item("a", as_of=5)
    late = SEGMENTS[5].timestamp + 1
    both = {"marker": "S3", "type": "segment", "ref": "9", "verified": True, "published_at": late}
    seg_late_pub = {"marker": "S4", "type": "segment", "ref": "4", "verified": True, "published_at": late}
    estimate = {"marker": "E1", "type": "estimate", "ref": "x", "verified": True, "published_at": late}
    assert time_violations(i, result("a", citations=[both, seg_late_pub, estimate, seg(2)]), SEGMENTS) == ["S3", "S4", "E1"]


def test_cost_per_question_divides_by_all_pairs_and_missing_reported():
    items = [item("a"), item("b"), item("c")]
    results = [result("a"), ItemResult(item_id="b", status=None, error={"code": "x", "message": ""})]
    summary = summarize(items, results, SEGMENTS)
    assert summary["cost_usd"]["per_question"] == pytest.approx(0.15 / 2)
    assert summary["missing"] == ["c"]


def test_numeric_citation_check_rate_counts_only_citations_in_sentences_with_numbers():
    i = item("a")
    r = result("a", citations=[seg(3), seg(4, verified=False)])
    r.answer = "매출이 5% 늘었습니다. [S3] 경영진은 낙관적이라고 했습니다. [S4]"
    summary = summarize([i], [r], SEGMENTS)
    assert summary["numeric_citation_check_rate"] == 1.0
    assert summary["assistant_citation_check_rate"] == 0.5
    r2 = result("a", citations=[seg(4)])
    r2.answer = "낙관적이라고 했습니다. [S4]"
    assert summarize([i], [r2], SEGMENTS)["numeric_citation_check_rate"] is None


def test_errored_expected_refusal_counts_in_errors_only():
    i = item("r", group="refusal", status="refused", reason="investment_advice")
    r = result("r", status=None, error={"code": "llm_timeout", "message": ""}, first=None)
    summary = summarize([i], [r], SEGMENTS)
    assert summary["errors"] == 1 and summary["refusals"]["missed"] == 0


def test_judge_cost_and_answered_only_first_token_and_models():
    items = [item("a"), item("b", group="refusal", status="refused", reason="investment_advice")]
    results = [result("a", first=100), result("b", status="refused", first=900)]
    summary = summarize(items, results, SEGMENTS, judge_usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert summary["cost_usd"]["judge_total"] == pytest.approx(2.25)
    assert summary["latency_ms"]["answered_first_token_p50"] == 100
    assert summary["generation_model"] == "gpt-6-luna" and summary["judge_model"] == "gpt-5.4-mini"
