"""Agent node that initializes routing and external-RAG defaults."""

from __future__ import annotations

from config import get_settings
from .route_decision import route_decision
from ..state import AgentState


async def agent(state: AgentState) -> AgentState:
    settings = get_settings()
    routed_state = await route_decision(state)

    return {
        **routed_state,
        "chunk_timestamp": state.get("chunk_timestamp", 0),
        "use_external_rag": state.get("use_external_rag", False),
        "rag_decision_confidence": state.get("rag_decision_confidence", 0.0),
        "retrieval_reason": state.get("retrieval_reason", ""),
        "external_query": state.get("external_query", ""),
        "rewrite_count": state.get("rewrite_count", 0),
        "external_retrieval_attempts": state.get("external_retrieval_attempts", 0),
        "preferred_sources": state.get("preferred_sources", []),
        "lookback_days": state.get("lookback_days", settings.rag_external_default_lookback_days),
        "external_docs": state.get("external_docs", []),
        "external_doc_scores": state.get("external_doc_scores", []),
        "has_external_evidence": state.get("has_external_evidence", False),
        "should_rewrite": state.get("should_rewrite", False),
        "rewrite_reason": state.get("rewrite_reason", ""),
    }
