"""backend 가 보내는 질의응답 요청 모델. 외부 요청에 backend 가 확정한 user_id·as_of_epoch 가 더해진 형태다."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

MAX_QUESTION_CHARS = 500
# 후속 질문 3회까지 허용하므로 앞선 질문·답은 최대 3쌍이다.
MAX_HISTORY_MESSAGES = 6

SuggestedQuestionId = Literal["summary", "vs_last_quarter", "guidance", "vs_expectations", "risks"]


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class AskRequest(BaseModel):
    user_id: str = Field(min_length=1)
    ticker: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10)]
    call_id: str = Field(min_length=1)
    as_of_sequence: int = Field(ge=0)
    as_of_epoch: int = Field(gt=0)
    anchor_sequence: int | None = Field(default=None, ge=0)
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)]
    suggested_question_id: SuggestedQuestionId | None = None
    history: list[HistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_MESSAGES)

    @model_validator(mode="after")
    def _anchor_not_after_as_of(self) -> AskRequest:
        if self.anchor_sequence is not None and self.anchor_sequence > self.as_of_sequence:
            raise ValueError("anchor_sequence 는 as_of_sequence 보다 클 수 없습니다")
        return self
