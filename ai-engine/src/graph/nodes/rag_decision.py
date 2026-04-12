"""LLM-based decision node for whether external RAG is needed."""

from __future__ import annotations

import json

from config import get_settings
from core.gemini_client import gemini_client
from core.token_budgeter import estimate_tokens
from models.rag_models import ExternalRagDecision
from ..state import AgentState

_RAG_DECISION_SYSTEM_PROMPT = """You decide whether external evidence retrieval is needed for
earnings-call chunk analysis.

Return JSON only with these fields:
- use_external_rag
- decision_confidence
- retrieval_reason
- external_query
- preferred_sources
- lookback_days

Rules:
- Use external RAG only when recent external evidence would materially improve interpretation.
- Do not request RAG for standalone chunks that are already self-contained.
- preferred_sources must only contain: news, filing, press_release, ir
- lookback_days must be between 1 and 30
- external_query must be concise and optimized for retrieval
"""


def _build_rag_decision_prompt(state: AgentState) -> str:
    context_lines = [
        f"Ticker: {state['ticker']}",
        f"Section type: {state.get('section_type') or 'OTHER'}",
        f"Chunk timestamp: {state.get('chunk_timestamp', 0)}",
        f"Novelty score: {state.get('novelty_score', 0.0):.4f}",
        f"Important chunk: {state.get('important_chunk', False)}",
    ]
    market_data = state.get("current_market_data")
    if market_data is not None:
        context_lines.append(
            "Market data: " + json.dumps(market_data.model_dump(exclude_none=True), separators=(",", ":"))
        )

    prior_chunks = state.get("context_chunks", [])[-3:]
    prompt_parts = ["\n".join(context_lines)]
    if prior_chunks:
        prompt_parts.append("## Recent transcript context")
        prompt_parts.extend(
            f"[Chunk {record.sequence}] {record.text_chunk}" for record in prior_chunks
        )
    prompt_parts.extend(["## Current chunk", state["current_chunk"]])
    prompt_parts.append(
        "Decide if recent external evidence such as news, filings, press releases, or IR materials "
        "is needed to interpret this chunk."
    )
    prompt_parts.append(
        "## Output contract\n"
        '{\n'
        '  "use_external_rag": true,\n'
        '  "decision_confidence": 0.0,\n'
        '  "retrieval_reason": "<short reason>",\n'
        '  "external_query": "<query>",\n'
        '  "preferred_sources": ["news"],\n'
        '  "lookback_days": 7\n'
        '}'
    )
    return "\n".join(prompt_parts)


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

    prompt = _build_rag_decision_prompt(state)
    config = {
        "system_instruction": _RAG_DECISION_SYSTEM_PROMPT,
        "max_output_tokens": settings.rag_decision_max_output_tokens,
        "response_mime_type": settings.gemini_response_mime_type,
        "thinking_level": settings.rag_decision_thinking_level,
    }

    try:
        raw_text = await gemini_client.generate_content(
            model=state["primary_model"],
            contents=prompt,
            config=config,
        )
        decision = ExternalRagDecision(**json.loads(raw_text))
    except Exception:
        return {
            **state,
            "rag_decision_contents": prompt,
            "rag_decision_result_text": "",
            "use_external_rag": False,
            "rag_decision_confidence": 0.0,
            "retrieval_reason": "rag_decision_failed",
            "external_query": "",
            "preferred_sources": [],
            "lookback_days": settings.rag_external_default_lookback_days,
            "llm_call_count": state.get("llm_call_count", 0) + 1,
            "estimated_prompt_tokens_consumed": state.get("estimated_prompt_tokens_consumed", 0)
            + estimate_tokens(prompt),
            "estimated_output_tokens_consumed": state.get("estimated_output_tokens_consumed", 0)
            + settings.rag_decision_max_output_tokens,
        }

    lookback_days = min(
        max(1, decision.lookback_days),
        settings.rag_external_max_lookback_days,
    )
    external_query = decision.external_query or f"{state['ticker']} {state['current_chunk']}".strip()

    return {
        **state,
        "rag_decision_contents": prompt,
        "rag_decision_result_text": raw_text,
        "use_external_rag": decision.use_external_rag,
        "rag_decision_confidence": decision.decision_confidence,
        "retrieval_reason": decision.retrieval_reason,
        "external_query": external_query,
        "preferred_sources": decision.preferred_sources,
        "lookback_days": lookback_days,
        "llm_call_count": state.get("llm_call_count", 0) + 1,
        "estimated_prompt_tokens_consumed": state.get("estimated_prompt_tokens_consumed", 0)
        + estimate_tokens(prompt),
        "estimated_output_tokens_consumed": state.get("estimated_output_tokens_consumed", 0)
        + settings.rag_decision_max_output_tokens,
    }
