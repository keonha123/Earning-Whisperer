"""Decision node for whether external evidence RAG is needed."""

from __future__ import annotations

import re

try:
    from config import get_settings
    from models.rag_models import ExternalRagDecision
    from src.graph.state import AgentState
except ImportError:  # pragma: no cover
    from ....config import get_settings
    from ....models.rag_models import ExternalRagDecision
    from ..state import AgentState


_RAG_TRIGGER_TERMS = {
    "guidance", "outlook", "forecast", "margin", "revenue", "capex", "demand", "supply",
    "backlog", "inventory", "pricing", "competition", "competitor", "customer", "contract",
    "regulatory", "sec", "fda", "lawsuit", "antitrust", "tariff", "export", "china",
    "ai", "accelerator", "cloud", "semiconductor", "shortage", "recall",
}
_FILING_TERMS = {"10-k", "10-q", "8-k", "filing", "sec", "debt", "dilution", "cash", "guidance"}
_NEWS_TERMS = {"lawsuit", "regulatory", "tariff", "contract", "customer", "recall", "export", "china"}
_IR_TERMS = {"guidance", "outlook", "investor", "presentation", "margin", "capex"}


async def rag_decision(state: AgentState) -> AgentState:
    settings = get_settings()
    if not settings.rag_enabled:
        return {
            **state,
            "use_external_rag": False,
            "rag_decision_confidence": 1.0,
            "retrieval_reason": "rag_disabled",
            "external_query": "",
            "preferred_sources": [],
            "lookback_days": settings.rag_external_default_lookback_days,
        }

    decision = _heuristic_decision(state)
    lookback_days = min(max(1, decision.lookback_days), settings.rag_external_max_lookback_days)
    return {
        **state,
        "use_external_rag": decision.use_external_rag,
        "rag_decision_confidence": decision.decision_confidence,
        "retrieval_reason": decision.retrieval_reason,
        "external_query": decision.external_query,
        "preferred_sources": decision.preferred_sources,
        "lookback_days": lookback_days,
    }


def _heuristic_decision(state: AgentState) -> ExternalRagDecision:
    ticker = str(state.get("ticker") or "UNKNOWN").upper()
    chunk = str(state.get("current_chunk") or "")
    text_l = chunk.lower()
    tokens = set(re.findall(r"[a-z0-9-]{3,}", text_l))
    triggers = sorted(tokens & _RAG_TRIGGER_TERMS)
    important = bool(state.get("important_chunk")) or int(state.get("request_priority", 5) or 5) >= 8
    source_type = str(state.get("source_type") or "").upper()
    section_type = str(state.get("section_type") or "").upper()
    use_rag = bool(triggers) and (important or section_type == "Q_AND_A" or source_type in {"NEWS", "FILING", "EARNINGS_CALL"})
    preferred: list[str] = []
    if tokens & _FILING_TERMS:
        preferred.append("filing")
    if tokens & _NEWS_TERMS:
        preferred.append("news")
    if tokens & _IR_TERMS:
        preferred.append("ir")
    if use_rag and "news" not in preferred:
        preferred.append("news")
    if not preferred and use_rag:
        preferred = ["news", "filing", "ir"]
    focus_terms = " ".join(triggers[:8]) if triggers else chunk[:120]
    query = f"{ticker} {focus_terms}".strip()
    confidence = 0.78 if use_rag and important else 0.62 if use_rag else 0.35
    reason = "material_external_context_needed" if use_rag else "self_contained_or_low_materiality"
    return ExternalRagDecision(
        use_external_rag=use_rag,
        decision_confidence=confidence,
        retrieval_reason=reason,
        external_query=query,
        preferred_sources=preferred,
        lookback_days=14 if tokens & (_NEWS_TERMS | _FILING_TERMS) else 7,
    )


__all__ = ["rag_decision"]
