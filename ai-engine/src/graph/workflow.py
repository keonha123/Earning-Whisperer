"""Graph-based workflow with a no-dependency fallback implementation."""

from __future__ import annotations

from .nodes.adjudication_llm_call import adjudication_llm_call
from .nodes.build_prompt import build_prompt_node
from .nodes.parse_and_finalize import parse_and_finalize
from .nodes.primary_llm_call import primary_llm_call
from .nodes.review_gate import review_gate
from .nodes.route_decision import route_decision
from .state import AgentState

try:  # pragma: no cover - optional dependency
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - exercised when langgraph is absent
    END = None
    START = None
    StateGraph = None


class _FallbackAgent:
    async def ainvoke(self, state: AgentState) -> AgentState:
        state = await route_decision(state)
        state = await build_prompt_node(state)
        state = await primary_llm_call(state)
        state = await review_gate(state)
        if state.get("needs_review"):
            state = await adjudication_llm_call(state)
        state = await parse_and_finalize(state)
        return state


def _review_edge(state: AgentState) -> str:
    return "adjudication_llm_call" if state.get("needs_review") else "parse_and_finalize"


if StateGraph is None:  # pragma: no cover - depends on environment
    agent = _FallbackAgent()
else:  # pragma: no cover - depends on environment
    agent_builder = StateGraph(AgentState)
    agent_builder.add_node("route_decision", route_decision)
    agent_builder.add_node("build_prompt", build_prompt_node)
    agent_builder.add_node("primary_llm_call", primary_llm_call)
    agent_builder.add_node("review_gate", review_gate)
    agent_builder.add_node("adjudication_llm_call", adjudication_llm_call)
    agent_builder.add_node("parse_and_finalize", parse_and_finalize)

    agent_builder.add_edge(START, "route_decision")
    agent_builder.add_edge("route_decision", "build_prompt")
    agent_builder.add_edge("build_prompt", "primary_llm_call")
    agent_builder.add_edge("primary_llm_call", "review_gate")
    agent_builder.add_conditional_edges(
        "review_gate",
        _review_edge,
        {
            "adjudication_llm_call": "adjudication_llm_call",
            "parse_and_finalize": "parse_and_finalize",
        },
    )
    agent_builder.add_edge("adjudication_llm_call", "parse_and_finalize")
    agent_builder.add_edge("parse_and_finalize", END)
    agent = agent_builder.compile()
