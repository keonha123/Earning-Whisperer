import json

import pytest

from eval.__main__ import main
from eval.compare import aggregate


def summary(accuracy, coverage=None):
    s = {"status_accuracy": accuracy, "evidence_recall": 0.5, "numeric_citation_check_rate": None,
         "latency_ms": {"first_token_p50": 100}, "cost_usd": {"per_question": 0.01}}
    if coverage is not None:
        s["judge"] = {"key_point_coverage": coverage, "citation_precision": 0.8}
    return s


def test_aggregate_mean_and_population_std():
    result = aggregate([summary(0.6, 0.5), summary(0.8, 0.7), summary(1.0, 0.9)])
    assert result["status_accuracy"]["mean"] == pytest.approx(0.8)
    assert result["status_accuracy"]["std"] == pytest.approx((0.08 / 3) ** 0.5)
    assert result["key_point_coverage"]["mean"] == pytest.approx(0.7)
    assert result["evidence_recall"]["std"] == 0
    assert result["numeric_citation_check_rate"] == {"mean": None, "std": None}


def test_aggregate_missing_judge_is_none():
    result = aggregate([summary(0.6), summary(0.8)])
    assert result["key_point_coverage"] == {"mean": None, "std": None}
    assert result["citation_precision"]["mean"] is None


def test_compare_command_prints_and_writes_nothing(tmp_path, capsys):
    paths = []
    for n, acc in enumerate([0.6, 0.8]):
        path = tmp_path / f"r{n}.json"
        path.write_text(json.dumps({"label": "x", "summary": summary(acc), "items": []}), encoding="utf-8")
        paths.append(str(path))
    assert main(["compare", *paths]) == 0
    assert "status_accuracy: 0.7000 ± 0.1000" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r0.json", "r1.json"]
