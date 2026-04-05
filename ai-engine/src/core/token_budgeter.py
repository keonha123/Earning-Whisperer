"""Token-budget planning utilities for transcript analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import get_settings


@dataclass(frozen=True)
class PromptBudgetPlan:
    estimated_tokens: int
    prompt_size: str
    initial_model: str
    review_model: str
    needs_compaction: bool


def estimate_tokens(text: str) -> int:
    """Approximate tokens conservatively using a chars-per-token heuristic."""

    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def plan_prompt_budget(text: str) -> PromptBudgetPlan:
    """Select a compaction policy and default route models from prompt size."""

    settings = get_settings()
    tokens = estimate_tokens(text)
    prompt_size = "small"
    if tokens > settings.analysis_target_chunk_tokens:
        prompt_size = "medium"
    if tokens > settings.analysis_max_prompt_tokens:
        prompt_size = "large"

    return PromptBudgetPlan(
        estimated_tokens=tokens,
        prompt_size=prompt_size,
        initial_model=settings.gemini_primary_model,
        review_model=settings.gemini_review_model,
        needs_compaction=tokens > settings.analysis_max_prompt_tokens,
    )
