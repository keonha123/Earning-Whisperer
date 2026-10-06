"""logothea-assistant 근거 조회 계약 (#112).

assistant 가 질문에 답할 때 쓰는 두 정보원(뉴스, 직전 콜 원문 문장)을 질문 시점 기준으로 돌려준다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NewsSearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str = Field(min_length=1)
    query: str = Field(min_length=1)
    as_of_epoch: int = Field(gt=0, description="이 시각(UTC epoch 초) 이후에 발행된 기사는 돌려주지 않는다")
    lookback_days: int = Field(default=30, ge=1, le=365)
    top_k: int = Field(default=6, ge=1, le=20)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class NewsSearchHit(BaseModel):
    doc_id: str
    title: str = ""
    source: str = ""
    url: str = ""
    published_at: int = 0
    snippet: str = ""
    score: float = 0.0


class NewsSearchResponse(BaseModel):
    ticker: str
    as_of_epoch: int
    hits: list[NewsSearchHit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PriorCallStatement(BaseModel):
    statement_id: str
    order: int
    topic: str
    speaker: str | None = None
    text: str


class PriorCallStatementsResponse(BaseModel):
    available: bool
    ticker: str
    document_id: str | None = None
    fiscal_quarter: str | None = None
    published_at_epoch: int | None = None
    statements: list[PriorCallStatement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "NewsSearchHit",
    "NewsSearchRequest",
    "NewsSearchResponse",
    "PriorCallStatement",
    "PriorCallStatementsResponse",
]
