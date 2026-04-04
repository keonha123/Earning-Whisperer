"""Primary Gemini Flash call node."""

from __future__ import annotations

from ....core.gemini_client import gemini_client
from ..state import AgentState


async def primary_llm_call(state: AgentState) -> AgentState:
    response_text = await gemini_client.generate_content(
        model=state["primary_model"],
        contents=state["contents"],
        config=state["primary_config"],
    )

    return {
        **state,
        "primary_result_text": response_text,
        "llm_call_count": state.get("llm_call_count", 0) + 1,
        "estimated_prompt_tokens_consumed": state["estimated_prompt_tokens"],
        "estimated_output_tokens_consumed": state["primary_config"]["max_output_tokens"],
    }
