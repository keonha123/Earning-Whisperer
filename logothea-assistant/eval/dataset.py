"""평가 질문셋 모델과 검증기."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from eval.transcript import EvalSegment

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "wmt_q2fy27.json"

Group = Literal["answerable", "no_evidence", "time", "refusal", "facts_only", "follow_up", "suggested"]
ExpectedStatus = Literal["answered", "refused", "no_evidence"]

# 스펙 4절의 묶음별 문항 수 하한.
GROUP_MINIMUMS: dict[str, int] = {
    "answerable": 22, "no_evidence": 6, "time": 5, "refusal": 6, "facts_only": 3, "follow_up": 4, "suggested": 10,
}


class EvalTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class EvalItem(BaseModel):
    id: str
    group: Group
    question: str
    as_of_sequence: int = Field(ge=0)
    anchor_sequence: int | None = None
    suggested_question_id: str | None = None
    history: list[EvalTurn] = Field(default_factory=list)
    expected_status: ExpectedStatus
    expected_refusal_reason: str | None = None
    # 정답 요점 2~4개. 수치가 있으면 원문 기준(조정/GAAP, 전년 대비 등)까지 적는다.
    key_points: list[str] = Field(default_factory=list)
    # 정답 근거 세그먼트 sequence. 근거 재현율 계산에 쓴다.
    gold_sequences: list[int] = Field(default_factory=list)
    note: str = ""


class EvalDataset(BaseModel):
    name: str
    ticker: str
    call_started_at: str
    items: list[EvalItem]


def load_dataset(path: Path) -> EvalDataset:
    return EvalDataset.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def validate_dataset(dataset: EvalDataset, segments: list[EvalSegment]) -> list[str]:
    errors: list[str] = []
    last = len(segments) - 1
    seen: set[str] = set()
    for item in dataset.items:
        tag = f"[{item.id}]"
        if item.id in seen:
            errors.append(f"{tag} 중복 id")
        seen.add(item.id)
        if item.as_of_sequence > last:
            errors.append(f"{tag} as_of_sequence {item.as_of_sequence} 가 마지막 세그먼트 {last} 보다 큼")
        if item.anchor_sequence is not None and item.anchor_sequence > item.as_of_sequence:
            errors.append(f"{tag} anchor_sequence 가 as_of_sequence 보다 큼")
        late = [s for s in item.gold_sequences if s > item.as_of_sequence or s > last]
        if late:
            errors.append(f"{tag} 정답 근거 {late} 가 as_of 이후이거나 없는 세그먼트")
        if item.expected_status == "answered":
            if not 2 <= len(item.key_points) <= 4:
                errors.append(f"{tag} answered 문항은 정답 요점 2~4개가 필요함")
            if not item.gold_sequences:
                errors.append(f"{tag} answered 문항은 정답 근거가 1개 이상 필요함")
        if item.expected_status == "refused" and not item.expected_refusal_reason:
            errors.append(f"{tag} refused 문항은 expected_refusal_reason 이 필요함")
        if item.group == "suggested" and not item.suggested_question_id:
            errors.append(f"{tag} suggested 문항은 suggested_question_id 가 필요함")
        if item.group == "follow_up" and not item.history:
            errors.append(f"{tag} follow_up 문항은 history 가 필요함")
    return errors
