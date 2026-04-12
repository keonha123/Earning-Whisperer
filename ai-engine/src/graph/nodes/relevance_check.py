"""Evidence-check node for deciding generate vs. external query rewrite."""

from __future__ import annotations

from config import get_settings
from ..state import AgentState


async def relevance_check(state: AgentState) -> AgentState:
    has_external_evidence = bool(state.get("external_docs"))
    settings = get_settings()
    can_rewrite = (
        state.get("rewrite_count", 0) < settings.rag_max_rewrites
        and state.get("use_external_rag", False)
    )

    if has_external_evidence:
        rewrite_reason = ""
    elif can_rewrite:
        rewrite_reason = "low_relevance"
    else:
        rewrite_reason = "rewrite_budget_exhausted"

    return {
        **state,
        "has_external_evidence": has_external_evidence,
        "should_rewrite": (not has_external_evidence) and can_rewrite,
        "rewrite_reason": rewrite_reason,
    }
