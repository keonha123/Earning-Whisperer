"""LLM 채점: 정답 요점 충족(요점별 present/contradicted/absent)과 인용 정밀도(인용 원문이 그 문장을 뒷받침하는가).

점수 척도(1~5)는 쓰지 않는다. 요점별 예/아니오 판정이 채점자 간 일치도가 높고, 무엇이 틀렸는지 바로 보인다.
채점 모델은 생성 모델과 다르게 둔다(자기 채점 편향 회피).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from assistant.citations import find_markers, split_sentences
from assistant.llm import LLMClient, Message, Usage
from eval.dataset import EvalItem
from eval.runner import ItemResult


class PointVerdict(BaseModel):
    point_index: int
    verdict: Literal["present", "contradicted", "absent"]


class CitationVerdict(BaseModel):
    marker: str
    supported: bool


class Judgment(BaseModel):
    points: list[PointVerdict]
    citations: list[CitationVerdict]


JUDGE_SYSTEM_PROMPT = """너는 어닝콜 질의응답 답변의 채점자다. 판단은 주어진 자료만으로 한다.
1. 정답 요점마다 답변에 그 내용이 있으면 present, 반대되는 내용이 있으면 contradicted, 없으면 absent 로 판정한다.
   수치는 기준(조정/GAAP, 전년 대비 등)까지 맞아야 present 다. 표현이 달라도 뜻이 같으면 present 다.
   - 답변 스스로가 그 내용을 단정해 말할 때만 present 다. 질문이나 얼버무린 표현(~일 수 있다, ~인지 확인되지 않는다)은 present 가 아니다.
   - 요점의 일부만 다뤘으면 absent 다.
   - 수치는 답변이 쓰는 정밀도로 반올림했을 때 같아야 present 다. 값이 다르면 contradicted 다.
2. 인용 표시마다, 그 표시가 쓰인 문장의 주장을 인용 원문이 뒷받침하면 supported=true, 아니면 false 다.
   원문에 없는 수치나 원문과 다른 방향(증가/감소)을 말하면 false 다.
   supported 는 인용 원문에 적힌 내용만으로 판단한다. 네가 아는 외부 지식으로 보충하지 않는다.
3. 모든 요점과 모든 인용 표시에 판정을 하나씩 낸다."""


def normalize_judgment(judgment: Judgment, item: EvalItem, result: ItemResult) -> tuple[Judgment, list[str]]:
    """채점 결과를 문항 구조에 맞춘다: 요점은 인덱스마다 하나, 인용은 실제 있는 표시마다 하나."""
    issues: list[str] = []
    count = len(item.key_points)
    first_points: dict[int, PointVerdict] = {}
    for verdict in judgment.points:
        index = verdict.point_index
        if not 0 <= index < count:
            issues.append(f"out-of-range point {index}")
        elif index in first_points:
            issues.append(f"duplicate point {index}")
        else:
            first_points[index] = verdict
    points = []
    for index in range(count):
        if index in first_points:
            points.append(first_points[index])
        else:
            issues.append(f"missing point {index}")
            points.append(PointVerdict(point_index=index, verdict="absent"))

    markers = _unique_markers(result)
    first_cites: dict[str, CitationVerdict] = {}
    for verdict in judgment.citations:
        if verdict.marker not in markers:
            issues.append(f"dropped invented marker {verdict.marker}")
        elif verdict.marker in first_cites:
            issues.append(f"duplicate marker {verdict.marker}")
        else:
            first_cites[verdict.marker] = verdict
    citations = []
    for marker in markers:
        if marker in first_cites:
            citations.append(first_cites[marker])
        else:
            issues.append(f"missing marker {marker}")
            citations.append(CitationVerdict(marker=marker, supported=False))
    return Judgment(points=points, citations=citations), issues


def _unique_markers(result: ItemResult) -> list[str]:
    markers: list[str] = []
    for citation in result.citations:
        marker = citation.get("marker", "")
        if marker and marker not in markers:
            markers.append(marker)
    return markers


def should_judge(item: EvalItem, result: ItemResult) -> bool:
    return item.expected_status == "answered" and result.error is None and bool(result.answer.strip())


def _build_prompt(item: EvalItem, result: ItemResult) -> str:
    lines = [f"질문: {item.question}", "", "정답 요점:"]
    lines += [f"{index}. {point}" for index, point in enumerate(item.key_points)]
    lines += ["", "답변:", result.answer, ""]
    sentences = split_sentences(result.answer)
    quotes: dict[str, str] = {}
    for citation in result.citations:
        quotes.setdefault(citation.get("marker", ""), citation.get("quote") or "(없음)")
    quotes.pop("", None)
    lines.append("인용:" if quotes else "인용: 없음")
    for marker, quote in quotes.items():
        lines.append(f"[{marker}] 인용 원문: {quote}")
        for sentence in sentences:
            if marker in find_markers(sentence):
                lines.append(f"[{marker}] 쓰인 문장: {sentence}")
    return "\n".join(lines)


async def judge_item_with_issues(llm: LLMClient, item: EvalItem, result: ItemResult) -> tuple[Judgment, Usage, list[str]]:
    messages = [Message("system", JUDGE_SYSTEM_PROMPT), Message("user", _build_prompt(item, result))]
    judgment, usage = await llm.parse(messages, Judgment)
    normalized, issues = normalize_judgment(judgment, item, result)
    return normalized, usage, issues


async def judge_item(llm: LLMClient, item: EvalItem, result: ItemResult) -> tuple[Judgment, Usage]:
    judgment, usage, _ = await judge_item_with_issues(llm, item, result)
    return judgment, usage
