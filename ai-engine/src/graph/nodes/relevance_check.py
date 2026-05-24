"""Evidence relevance node for RAG routing."""

from __future__ import annotations

try:
    from config import get_settings
    from src.graph.state import AgentState
except ImportError:  # pragma: no cover
    from ....config import get_settings
    from ..state import AgentState


async def relevance_check(state: AgentState) -> AgentState:
    settings = get_settings()
    docs = state.get("external_docs", []) or []
    has_external_evidence = bool(docs)
    can_rewrite = state.get("external_retrieval_attempts", 0) <= settings.rag_max_rewrites and state.get("use_external_rag", False)
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


__all__ = ["relevance_check"]
