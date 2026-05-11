"""Retrieval node for external evidence RAG."""

from __future__ import annotations

from core.external_retriever import external_retriever
from ..state import AgentState


async def retrieve(state: AgentState) -> AgentState:
    try:
        documents = external_retriever.retrieve(
            query=state.get("external_query", state["current_chunk"]),
            ticker=state["ticker"],
            chunk_timestamp=state.get("chunk_timestamp", 0),
            preferred_sources=state.get("preferred_sources", []),
            lookback_days=state.get("lookback_days", 7),
        )
    except Exception:
        documents = []
    return {
        **state,
        "external_docs": documents,
        "external_doc_scores": [doc.score for doc in documents],
        "external_retrieval_attempts": state.get("external_retrieval_attempts", 0) + 1,
    }
