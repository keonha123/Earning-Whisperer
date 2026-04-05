"""Final parse node."""

from __future__ import annotations

from ....core.gemini_client import gemini_client
from ..state import AgentState


async def parse_and_finalize(state: AgentState) -> AgentState:
    if state.get("review_result_text"):
        result = gemini_client.parse_response_text(state["review_result_text"])
        result.model_route = f"{state['primary_model']}->{state['review_model']}"
        return {
            **state,
            "result": result,
            "estimated_prompt_tokens": state.get("estimated_prompt_tokens_consumed", 0),
            "estimated_output_tokens": state.get("estimated_output_tokens_consumed", 0),
        }

    result = state.get("parsed_primary_result") or state.get("result")
    if result is None:
        # When review is capped at one live LLM call, a malformed first pass
        # should degrade to a neutral fallback instead of crashing the pipeline.
        fallback = gemini_client._fallback_result()
        fallback.model_route = f"{state['primary_model']}->fallback"
        return {
            **state,
            "result": fallback,
            "estimated_prompt_tokens": state.get(
                "estimated_prompt_tokens_consumed",
                state.get("estimated_prompt_tokens", 0),
            ),
            "estimated_output_tokens": state.get(
                "estimated_output_tokens_consumed",
                state["primary_config"]["max_output_tokens"],
            ),
        }

    result.model_route = result.model_route or state["primary_model"]
    return {
        **state,
        "result": result,
        "estimated_prompt_tokens": state.get(
            "estimated_prompt_tokens_consumed",
            state.get("estimated_prompt_tokens", 0),
        ),
        "estimated_output_tokens": state.get(
            "estimated_output_tokens_consumed",
            state["primary_config"]["max_output_tokens"],
        ),
    }
