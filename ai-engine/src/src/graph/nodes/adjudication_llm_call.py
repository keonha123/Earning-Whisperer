"""Adjudication call node for escalations to Gemini Pro."""

from __future__ import annotations

from ....config import get_settings
from ....core.gemini_client import gemini_client
from ....core.prompt_builder import build_prompt
from ....core.token_budgeter import estimate_tokens
from ..state import AgentState


async def adjudication_llm_call(state: AgentState) -> AgentState:
    settings = get_settings()
    if not state.get("needs_review"):
        return state
    if state.get("llm_call_count", 0) >= settings.llm_router_max_calls_per_chunk:
        return state

    review_prompt = build_prompt(
        ticker=state["ticker"],
        current_chunk=state["current_chunk"],
        context_chunks=state.get("context_chunks", []),
        market_data=state.get("current_market_data"),
        prompt_profile="adjudication",
        context_policy="adjudication",
        phase1_score=state.get("phase1_raw_score"),
        previous_result=state.get("parsed_primary_result"),
        review_reason=state.get("review_reason"),
    )
    review_prompt_tokens = estimate_tokens(review_prompt)
    response_text = await gemini_client.generate_content(
        model=state["review_model"],
        contents=review_prompt,
        config=state["review_config"],
    )

    return {
        **state,
        "review_contents": review_prompt,
        "review_result_text": response_text,
        "llm_call_count": state.get("llm_call_count", 0) + 1,
        "estimated_prompt_tokens_consumed": state.get("estimated_prompt_tokens_consumed", 0)
        + review_prompt_tokens,
        "estimated_output_tokens_consumed": state.get("estimated_output_tokens_consumed", 0)
        + state["review_config"]["max_output_tokens"],
    }
