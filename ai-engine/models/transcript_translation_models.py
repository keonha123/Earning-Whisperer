from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TranslationTerm(BaseModel):
    """번역어를 고정할 용어 1개. backend 가 세그먼트 원문에서 매칭한 것만 보낸다."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    term: str = Field(min_length=1, max_length=120)
    ko: str = Field(min_length=1, max_length=120)

    @field_validator("term", "ko")
    @classmethod
    def _collapse_whitespace(cls, value: str) -> str:
        return " ".join(value.split())


class TranscriptTranslateRequest(BaseModel):
    """앞뒤 공백을 걷어낸 뒤 길이를 검사한다. 공백뿐인 값은 422 로 거부된다."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ticker: str = Field(min_length=1, max_length=16)
    call_id: str | None = None
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4000)
    terms: list[TranslationTerm] = Field(default_factory=list, max_length=50)

    @field_validator("text")
    @classmethod
    def _collapse_whitespace(cls, value: str) -> str:
        return " ".join(value.split())


class TranscriptTranslateResponse(BaseModel):
    """번역 결과.

    실패해도 HTTP 200 이다. `available=false` 와 `warnings` 로 사유를 알린다.
    `text_ko` 는 실패 시 null 이며, 원문을 대신 넣지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    available: bool
    sequence: int
    text_ko: str | None = None
    terms_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = ["TranscriptTranslateRequest", "TranscriptTranslateResponse", "TranslationTerm"]
