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
2. 인용 표시마다, 그 표시가 쓰인 문장의 주장을 인용 원문이 뒷받침하면 supported=true, 아니면 false 다.
   원문에 없는 수치나 원문과 다른 방향(증가/감소)을 말하면 false 다.
3. 모든 요점과 모든 인용 표시에 판정을 하나씩 낸다."""


def should_judge(item: EvalItem, result: ItemResult) -> bool:
    return item.expected_status == "answered" and result.error is None and bool(result.answer.strip())


async def judge_item(llm: LLMClient, item: EvalItem, result: ItemResult) -> tuple[Judgment, Usage]:
    lines = [f"질문: {item.question}", "", "정답 요점:"]
    lines += [f"{index}. {point}" for index, point in enumerate(item.key_points)]
    lines += ["", "답변:", result.answer, "", "인용:"]
    sentences = split_sentences(result.answer)
    for citation in result.citations:
        marker = citation.get("marker", "")
        lines.append(f"[{marker}] 인용 원문: {citation.get('quote') or '(없음)'}")
        for sentence in sentences:
            if marker in find_markers(sentence):
                lines.append(f"[{marker}] 쓰인 문장: {sentence}")
    messages = [Message("system", JUDGE_SYSTEM_PROMPT), Message("user", "\n".join(lines))]
    return await llm.parse(messages, Judgment)
