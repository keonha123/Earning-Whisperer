"""Workflow state definitions."""

from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired

from core.external_retriever import ExternalRetrievedDocument
from models.signal_models import GeminiAnalysisResult


class GeminiConfig(TypedDict, total=False):
    system_instruction: str
    max_output_tokens: int
    response_mime_type: str
    thinking_level: str


class AgentState(TypedDict, total=False):
    # Request / input context
    ticker: str
    current_chunk: str
    current_market_data: object
    context_chunks: list[object]
    chunk_timestamp: int
    section_type: object
    request_priority: int
    is_final: bool
    phase1_raw_score: float
    phase1_confidence: float

    # Routing / prompt profile
    route_profile: str
    context_policy: str
    novelty_score: float
    important_chunk: bool

    # External retrieval / RAG
    use_external_rag: bool
    rag_decision_confidence: float
    retrieval_reason: str
    external_query: str
    rewrite_count: int
    external_retrieval_attempts: int
    preferred_sources: list[str]
    lookback_days: int
    external_docs: list[ExternalRetrievedDocument]
    external_doc_scores: list[float]
    has_external_evidence: bool
    should_rewrite: bool
    rewrite_reason: str

    # LLM execution config
    primary_model: str
    review_model: str
    primary_config: GeminiConfig
    review_config: GeminiConfig
    llm_call_count: int

    # Prompt / raw model outputs
    contents: str
    review_contents: str
    primary_result_text: str
    review_result_text: str

    # Review / parse state
    primary_parse_failed: bool
    needs_review: bool
    review_reason: str
    parsed_primary_result: GeminiAnalysisResult

    # Final result
    result: GeminiAnalysisResult

    # Token / usage accounting
    estimated_prompt_tokens: int
    estimated_output_tokens: int
    estimated_prompt_tokens_consumed: int
    estimated_output_tokens_consumed: int

    # Optional raw RAG LLM artifacts
    rag_decision_contents: str
    rag_decision_result_text: str
    rewrite_contents: str
