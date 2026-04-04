"""Workflow state definitions."""

from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired

from ...models.signal_models import GeminiAnalysisResult


class GeminiConfig(TypedDict, total=False):
    system_instruction: str
    max_output_tokens: int
    response_mime_type: str
    thinking_level: str


class AgentState(TypedDict, total=False):
    ticker: str
    current_chunk: str
    current_market_data: object
    context_chunks: list[object]
    section_type: object
    request_priority: int
    is_final: bool
    phase1_raw_score: float
    phase1_confidence: float

    route_profile: str
    context_policy: str
    primary_model: str
    review_model: str
    primary_config: GeminiConfig
    review_config: GeminiConfig
    estimated_prompt_tokens: int
    estimated_output_tokens: int
    estimated_prompt_tokens_consumed: int
    estimated_output_tokens_consumed: int
    novelty_score: float
    important_chunk: bool

    contents: str
    review_contents: str
    primary_result_text: str
    review_result_text: str
    primary_parse_failed: bool
    needs_review: bool
    review_reason: str
    parsed_primary_result: GeminiAnalysisResult
    result: GeminiAnalysisResult
    llm_call_count: int
