"""Route-decision node for live Gemini routing."""

from __future__ import annotations

from ....config import get_settings
from ....core.llm_router import decide_route
from ....core.prompt_builder import SYSTEM_PROMPT
from ..state import AgentState


async def route_decision(state: AgentState) -> AgentState:
    settings = get_settings()
    decision = decide_route(
        current_chunk=state["current_chunk"],
        context_chunks=state.get("context_chunks", []),
        market_data=state.get("current_market_data"),
        section_type=state.get("section_type"),
        request_priority=state.get("request_priority", 5),
        is_final=state.get("is_final", False),
        phase1_raw_score=state.get("phase1_raw_score", 0.0),
    )

    return {
        **state,
        "route_profile": decision.route_profile,
        "context_policy": decision.context_policy,
        "primary_model": decision.primary_model,
        "review_model": decision.review_model,
        "primary_config": {
            "system_instruction": SYSTEM_PROMPT,
            "max_output_tokens": decision.primary_max_output_tokens,
            "response_mime_type": settings.gemini_response_mime_type,
            "thinking_level": decision.primary_thinking_level,
        },
        "review_config": {
            "system_instruction": SYSTEM_PROMPT,
            "max_output_tokens": decision.review_max_output_tokens,
            "response_mime_type": settings.gemini_response_mime_type,
            "thinking_level": decision.review_thinking_level,
        },
        "estimated_prompt_tokens": decision.estimated_prompt_tokens,
        "estimated_output_tokens": decision.primary_max_output_tokens,
        "estimated_prompt_tokens_consumed": 0,
        "estimated_output_tokens_consumed": 0,
        "novelty_score": decision.novelty_score,
        "important_chunk": decision.important_chunk,
        "primary_parse_failed": False,
        "needs_review": False,
        "llm_call_count": 0,
    }
