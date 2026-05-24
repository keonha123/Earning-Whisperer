"""Shared graph state aliases for the AI engine node pipeline."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    ticker: str
    current_chunk: str
    chunk_timestamp: int
    section_type: str
    source_type: str
    request_priority: int
    important_chunk: bool
    novelty_score: float
    external_query: str
    preferred_sources: list[str]
    lookback_days: int
    use_external_rag: bool
    rag_decision_confidence: float
    retrieval_reason: str
    external_docs: list[Any]
    external_doc_scores: list[float]
    external_retrieval_attempts: int
    has_external_evidence: bool
    should_rewrite: bool
    rewrite_reason: str


__all__ = ["AgentState"]
