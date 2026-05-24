"""Retrieval node for external evidence RAG."""

from __future__ import annotations

try:
    from core.external_retriever import external_retriever
    from src.graph.state import AgentState
except ImportError:  # pragma: no cover
    from ....core.external_retriever import external_retriever
    from ..state import AgentState


async def retrieve(state: AgentState) -> AgentState:
    if not state.get("use_external_rag", False):
        return {
            **state,
            "external_docs": [],
            "external_doc_scores": [],
            "external_retrieval_attempts": state.get("external_retrieval_attempts", 0),
        }
    try:
        documents = external_retriever.retrieve(
            query=state.get("external_query", state.get("current_chunk", "")),
            ticker=state.get("ticker", ""),
            chunk_timestamp=int(state.get("chunk_timestamp", 0) or 0),
            preferred_sources=state.get("preferred_sources", []),
            lookback_days=int(state.get("lookback_days", 7) or 7),
        )
    except Exception:
        documents = []
    return {
        **state,
        "external_docs": documents,
        "external_doc_scores": [doc.score for doc in documents],
        "external_retrieval_attempts": state.get("external_retrieval_attempts", 0) + 1,
    }


__all__ = ["retrieve"]
