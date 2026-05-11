"""LLM query rewrite node for low-relevance external retrieval results."""

from __future__ import annotations

import json

from config import get_settings
from core.gemini_client import gemini_client
from core.token_budgeter import estimate_tokens
from models.rag_models import ExternalQueryRewrite
from ..state import AgentState

_REWRITE_SYSTEM_PROMPT = """Rewrite the search query for external evidence retrieval.

Return JSON only with these fields:
- external_query
- rewrite_reason

Rules:
- Keep the query concise and retrieval-oriented
- Include the ticker and the key event or business topic
- Do not use markdown or extra prose
"""


def _build_rewrite_prompt(state: AgentState) -> str:
    prior_chunks = state.get("context_chunks", [])[-2:]
    lines = [
        f"Ticker: {state['ticker']}",
        f"Section type: {state.get('section_type') or 'OTHER'}",
        f"Current external query: {state.get('external_query', '')}",
        f"Rewrite reason: {state.get('rewrite_reason', '')}",
        "## Current chunk",
        state["current_chunk"],
    ]
    if prior_chunks:
        lines.append("## Recent transcript context")
        lines.extend(f"[Chunk {record.sequence}] {record.text_chunk}" for record in prior_chunks)
    lines.append("Rewrite the query so external news, filings, press releases, or IR docs are easier to find.")
    return "\n".join(lines)


async def rewrite(state: AgentState) -> AgentState:
    settings = get_settings()
    prompt = _build_rewrite_prompt(state)
    config = {
        "system_instruction": _REWRITE_SYSTEM_PROMPT,
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
        rewritten_query = ExternalQueryRewrite(**json.loads(raw_text)).external_query
    except Exception:
        rewritten_query = f"{state['ticker']} {state['current_chunk']}".strip()
        raw_text = ""

    return {
        **state,
        "rewrite_contents": prompt,
        "external_query": rewritten_query,
        "rewrite_count": state.get("rewrite_count", 0) + 1,
        "external_docs": [],
        "external_doc_scores": [],
        "llm_call_count": state.get("llm_call_count", 0) + 1,
        "estimated_prompt_tokens_consumed": state.get("estimated_prompt_tokens_consumed", 0)
        + estimate_tokens(prompt),
        "estimated_output_tokens_consumed": state.get("estimated_output_tokens_consumed", 0)
        + settings.rag_decision_max_output_tokens,
    }
