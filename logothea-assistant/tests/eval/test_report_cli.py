import json
from datetime import date

from eval.__main__ import estimate_cost_usd, main
from eval.report import render_markdown, write_report

SUMMARY = {
    "count": 2, "errors": 0, "status_accuracy": 0.5, "refusals": {"appropriate": 1, "inappropriate": 0, "missed": 0},
    "evidence_recall": 0.75, "citation_verified_rate": 1.0, "time_violations": {"a1": ["S9"]},
    "latency_ms": {"first_token_p50": 800, "first_token_p95": 1200, "total_p50": 4000, "total_p95": 6000},
    "cost_usd": {"total": 0.01, "per_question": 0.005},
    "by_group": {"answerable": {"count": 2, "status_accuracy": 0.5, "evidence_recall": 0.75}},
}
ROWS = [{"id": "a1", "group": "answerable", "expected_status": "answered", "status": "no_evidence", "error": None,
         "time_violations": ["S9"], "answer": "…"}]


def test_markdown_puts_time_violations_and_mismatches_first():
    text = render_markdown("baseline", SUMMARY, ROWS)
    assert text.startswith("# 평가 보고서 — baseline")
    assert text.index("시점 위반") < text.index("묶음별")
    assert "a1" in text and "S9" in text
    assert "| answerable | 2 | 50.0% | 75.0% |" in text


def test_write_report_names_files_by_date_and_label(tmp_path):
    json_path, md_path = write_report(tmp_path, "baseline", SUMMARY, ROWS, today=date(2026, 10, 7))
    assert json_path.name == "2026-10-07-baseline.json" and md_path.name == "2026-10-07-baseline.md"
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["count"] == 2


def test_cost_estimate_grows_with_items_and_judge():
    assert 0 < estimate_cost_usd(60, judge=False) < estimate_cost_usd(60, judge=True)


def test_run_without_yes_prints_estimate_and_sends_nothing(capsys, monkeypatch):
    import eval.__main__ as cli

    def forbidden(*args, **kwargs):
        raise AssertionError("요청을 보내면 안 됩니다")

    monkeypatch.setattr(cli, "seed_segments", forbidden)
    monkeypatch.setattr(cli, "AssistantRunner", forbidden)

    assert main(["run", "--label", "baseline"]) == 2
    out = capsys.readouterr().out
    assert "예상 비용" in out and "--yes" in out


def test_validate_command_passes_on_real_dataset(capsys):
    assert main(["validate"]) == 0
    assert "문제 없음" in capsys.readouterr().out


def test_run_rejects_non_positive_runs_and_limit(capsys):
    assert main(["run", "--label", "x", "--runs", "0"]) == 1
    assert main(["run", "--label", "x", "--limit", "0"]) == 1
    assert "1 이상" in capsys.readouterr().out


def test_full_fake_run_writes_report_with_runner_and_judge_errors(tmp_path, monkeypatch):
    import eval.__main__ as cli
    from assistant.llm import LLMError
    from eval.judge import CitationVerdict, Judgment, PointVerdict
    from eval.runner import ItemResult

    answered = [i for i in cli.load_dataset(cli.DATASET_PATH).items if i.expected_status == "answered"][:3]
    ids = [i.id for i in answered]
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "load_dataset", lambda path: type("D", (), {"items": answered, "ticker": "WMT"})())
    monkeypatch.setattr(cli, "validate_dataset", lambda dataset, segments: [])
    monkeypatch.setattr(cli, "seed_segments", lambda *a, **k: 0)
    monkeypatch.setattr(cli, "OpenAIClient", lambda **k: object())

    class FakeRunner:
        def __init__(self, *a, **k):
            pass

        def run_item(self, item):
            if item.id == ids[0]:
                raise RuntimeError("boom")
            return ItemResult(item_id=item.id, status="answered", answer="답변입니다.")

    async def fake_judge(llm, item, result):
        if item.id == ids[1]:
            raise LLMError("llm_timeout", "slow")
        return Judgment(points=[PointVerdict(point_index=0, verdict="present")], citations=[]), None, ["missing point 1"]

    monkeypatch.setattr(cli, "AssistantRunner", FakeRunner)
    monkeypatch.setattr(cli, "judge_item_with_issues", fake_judge)

    assert main(["run", "--label", "a/b c", "--judge", "--limit", "3", "--yes"]) == 0

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1 and files[0].name.endswith("-a-b-c.json")
    rows = {r["id"]: r for r in json.loads(files[0].read_text(encoding="utf-8"))["items"]}
    assert len(rows) == 3
    assert rows[ids[0]]["error"]["code"] == "runner_exception"
    assert rows[ids[1]]["judge_error"] == "llm_timeout"
    assert rows[ids[2]]["judge_issues"] == ["missing point 1"] and rows[ids[2]]["judgment"] is not None
