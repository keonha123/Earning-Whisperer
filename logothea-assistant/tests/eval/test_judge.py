from eval.dataset import EvalItem
from eval.judge import (JUDGE_SYSTEM_PROMPT, CitationVerdict, Judgment, PointVerdict, judge_item,
                        judge_item_with_issues, normalize_judgment, should_judge)
from eval.runner import ItemResult
from tests.fakes import FakeLLM


def _item(status="answered"):
    return EvalItem(id="a1", group="answerable", question="기존점 매출은?", as_of_sequence=5, expected_status=status,
                    expected_refusal_reason="investment_advice" if status == "refused" else None,
                    key_points=["미국 기존점 매출 2.6% 증가", "거래 건수가 이끔"] if status == "answered" else [],
                    gold_sequences=[3] if status == "answered" else [])


def _result(**overrides):
    data = dict(item_id="a1", status="answered", answer="미국 기존점 매출은 2.6% 늘었습니다 [S3]. 거래가 늘었습니다 [S3][N1].",
                citations=[{"marker": "S3", "quote": "Comp sales for Walmart U.S. were 2.6%, led by transactions."},
                           {"marker": "N1", "quote": "Walmart beats"}])
    data.update(overrides)
    return ItemResult(**data)


def test_should_judge_only_answered_items_without_errors():
    assert should_judge(_item(), _result())
    assert not should_judge(_item("refused"), _result(status="refused"))
    assert not should_judge(_item(), _result(error={"code": "x", "message": ""}))
    assert not should_judge(_item(), _result(answer=""))


async def test_judge_sends_points_sentences_and_quotes():
    expected = Judgment(points=[PointVerdict(point_index=0, verdict="present"), PointVerdict(point_index=1, verdict="present")],
                        citations=[CitationVerdict(marker="S3", supported=True), CitationVerdict(marker="N1", supported=False)])
    llm = FakeLLM(parsed=expected)

    judgment, usage = await judge_item(llm, _item(), _result())

    assert judgment == expected
    system, user = llm.parse_calls[0]
    assert system.role == "system" and "present" in system.text and "contradicted" in system.text
    assert "0. 미국 기존점 매출 2.6% 증가" in user.text
    assert "1. 거래 건수가 이끔" in user.text
    assert "[S3] 인용 원문: Comp sales for Walmart U.S. were 2.6%, led by transactions." in user.text
    assert "[S3] 쓰인 문장: 미국 기존점 매출은 2.6% 늘었습니다 [S3]." in user.text
    assert "[N1] 쓰인 문장: 거래가 늘었습니다 [S3][N1]." in user.text


def test_normalize_fixes_duplicates_missing_out_of_range_and_invented():
    raw = Judgment(
        points=[PointVerdict(point_index=1, verdict="present"), PointVerdict(point_index=1, verdict="absent"),
                PointVerdict(point_index=7, verdict="present")],
        citations=[CitationVerdict(marker="N1", supported=True), CitationVerdict(marker="N1", supported=False),
                   CitationVerdict(marker="S9", supported=True)])
    fixed, issues = normalize_judgment(raw, _item(), _result())
    assert [(p.point_index, p.verdict) for p in fixed.points] == [(0, "absent"), (1, "present")]
    assert [(c.marker, c.supported) for c in fixed.citations] == [("S3", False), ("N1", True)]
    assert "missing point 0" in issues and "duplicate point 1" in issues
    assert "dropped invented marker S9" in issues and "missing marker S3" in issues


async def test_judge_item_with_issues_returns_normalized():
    llm = FakeLLM(parsed=Judgment(points=[], citations=[]))
    judgment, _usage, issues = await judge_item_with_issues(llm, _item(), _result())
    assert len(judgment.points) == 2 and len(judgment.citations) == 2 and issues


async def test_prompt_lists_duplicated_marker_once():
    result = _result(citations=[{"marker": "S3", "quote": "q1"}, {"marker": "S3", "quote": "q1"}])
    llm = FakeLLM(parsed=Judgment(points=[], citations=[]))
    await judge_item(llm, _item(), result)
    assert llm.parse_calls[0][1].text.count("[S3] 인용 원문:") == 1


async def test_prompt_without_citations_says_none():
    llm = FakeLLM(parsed=Judgment(points=[], citations=[]))
    await judge_item(llm, _item(), _result(citations=[]))
    assert "인용: 없음" in llm.parse_calls[0][1].text


def test_system_prompt_has_strict_rules():
    for phrase in ("단정해", "일부만 다뤘으면 absent", "반올림", "외부 지식"):
        assert phrase in JUDGE_SYSTEM_PROMPT
