"""Single LLM call node used by the graph workflow."""

from __future__ import annotations

from core.gemini_client import gemini_client
from ..state import AgentState


async def llm_call(state: AgentState) -> AgentState:
    model = state["model"].strip()
    contents = state["contents"]
    config = state.get("config", {})

    if not model:
        raise ValueError("state.model must be a non-empty string")
    if not isinstance(contents, str) or not contents.strip():
        raise ValueError("state.contents must be a non-empty string")

    response_text = await gemini_client.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    return {
        **state,
        "response_text": response_text,
    }
