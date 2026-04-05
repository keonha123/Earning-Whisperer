"""Prompt-building node."""

from __future__ import annotations

from ....config import get_settings
from ....core.prompt_builder import build_prompt
from ....core.token_budgeter import estimate_tokens
from ..state import AgentState


def _compact_prompt(prompt: str) -> str:
    settings = get_settings()
    max_chars = settings.analysis_max_prompt_tokens * 4
    if len(prompt) <= max_chars:
        return prompt

    head = prompt[: max_chars // 3]
    tail = prompt[-(max_chars - len(head) - 32) :]
    return f"{head}\n\n[...prompt compacted...]\n\n{tail}"


async def build_prompt_node(state: AgentState) -> AgentState:
    prompt = build_prompt(
        ticker=state["ticker"],
        current_chunk=state["current_chunk"],
        context_chunks=state.get("context_chunks", []),
        market_data=state.get("current_market_data"),
        prompt_profile=state["route_profile"],
        context_policy=state["context_policy"],
        phase1_score=state.get("phase1_raw_score"),
    )
    prompt = _compact_prompt(prompt)

    return {
        **state,
        "contents": prompt,
        "estimated_prompt_tokens": estimate_tokens(prompt),
    }
