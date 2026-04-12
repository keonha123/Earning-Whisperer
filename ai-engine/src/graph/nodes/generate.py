"""Generate node that preserves the existing review/finalize path."""

from __future__ import annotations

from .adjudication_llm_call import adjudication_llm_call
from .build_prompt import build_prompt_node
from .parse_and_finalize import parse_and_finalize
from .primary_llm_call import primary_llm_call
from .review_gate import review_gate
from ..state import AgentState


async def generate(state: AgentState) -> AgentState:
    state = await build_prompt_node(state)
    state = await primary_llm_call(state)
    state = await review_gate(state)
    if state.get("needs_review"):
        state = await adjudication_llm_call(state)
    return await parse_and_finalize(state)
