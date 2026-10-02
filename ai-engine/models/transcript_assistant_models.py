"""Contracts for asynchronous translation and single-turn, grounded transcript QA."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence_models import EvidenceCitation


class TranscriptIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ticker: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.^-]+$")
    call_id: str = Field(min_length=1, max_length=160)

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, value: str) -> str:
        return value.upper()


class TranslationTerm(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    term: str = Field(min_length=1, max_length=120)
    ko: str = Field(min_length=1, max_length=120)

    @field_validator("term", "ko")
    @classmethod
    def collapse_whitespace(cls, value: str) -> str:
        return " ".join(value.split())


class TranscriptTranslateRequest(TranscriptIdentity):
    # The standalone translation producer may not yet have a session identity.
    # QA still requires one, and callers patching a live session must match it.
    call_id: str | None = Field(default=None, min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=12000)
    terms: list[TranslationTerm] = Field(default_factory=list, max_length=50)


class TranscriptTranslateResponse(TranscriptIdentity):
    call_id: str | None = Field(default=None, min_length=1, max_length=160)
    sequence: int
    available: bool = False
    original_text: str
    text_ko: str | None = None
    terms_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TranscriptAskRequest(TranscriptIdentity):
    segment_sequences: list[int] = Field(min_length=1, max_length=10)
    segment_texts: list[str] = Field(min_length=1, max_length=10)
    question: str = Field(min_length=1, max_length=2000)
    as_of: datetime
    context_before: str = Field(default="", max_length=4000)
    context_after: str = Field(default="", max_length=4000)
    insufficient_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_segments(self):
        if len(self.segment_sequences) != len(self.segment_texts):
            raise ValueError("segment_sequences and segment_texts must have matching lengths")
        if any(i < 0 for i in self.segment_sequences) or len(set(self.segment_sequences)) != len(self.segment_sequences):
            raise ValueError("segment sequences must be unique nonnegative integers")
        if any(not text.strip() for text in self.segment_texts) or sum(map(len, self.segment_texts)) > 16000:
            raise ValueError("segments must be nonempty and at most 16000 characters combined")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return self


class AnswerCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_index: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=4000)


class TranscriptAskResponse(TranscriptIdentity):
    segment_sequences: list[int]
    available: bool = False
    answer_ko: str | None = None
    refused: bool = False
    refusal_reason: str | None = None
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GroundedAnswer(BaseModel):
    """A malformed, unsupported, or uncited model answer is never published."""
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["supported", "insufficient", "out_of_scope", "investment_advice"]
    answer_ko: str = Field(default="", max_length=6000)
    citations: list[AnswerCitation] = Field(default_factory=list, max_length=20)


class GlossaryTerm(BaseModel):
    term: str
    aliases: list[str] = Field(default_factory=list)
    ko: str
    definition_ko: str
    why_ko: str
    category: str


class GlossaryResponse(BaseModel):
    version: str
    terms: list[GlossaryTerm]
