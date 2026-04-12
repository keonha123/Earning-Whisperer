"""Graph-based workflow with an agentic RAG front-end and fallback mode."""

from __future__ import annotations

from .nodes.agent import agent as agent_node
from .nodes.generate import generate
from .nodes.rag_decision import rag_decision
from .nodes.relevance_check import relevance_check
from .nodes.retrieve import retrieve
from .nodes.rewrite import rewrite
from .state import AgentState

try:  # pragma: no cover - optional dependency
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - exercised when langgraph is absent
    END = None
    START = None
    StateGraph = None


def rag_decision_branch(state: AgentState) -> str:
    return "retrieve" if state.get("use_external_rag") else "generate"


def evidence_decision(state: AgentState) -> str:
    return "query_rewrite" if state.get("should_rewrite") else "generate"


class _FallbackAgent:
    async def ainvoke(self, state: AgentState) -> AgentState:
        state = await agent_node(state)
        state = await rag_decision(state)

        while True:
            if rag_decision_branch(state) == "retrieve":
                state = await retrieve(state)
                state = await relevance_check(state)
                if evidence_decision(state) == "query_rewrite":
                    state = await rewrite(state)
                    continue
            return await generate(state)


if StateGraph is None:  # pragma: no cover - depends on environment
    agent = _FallbackAgent()
else:  # pragma: no cover - depends on environment
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("rag_decision", rag_decision)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("relevance_check", relevance_check)
    workflow.add_node("query_rewrite", rewrite)
    workflow.add_node("generate", generate)

    workflow.add_edge(START, "agent")
    workflow.add_edge("agent", "rag_decision")
    workflow.add_conditional_edges(
        "rag_decision",
        rag_decision_branch,
        {
            "retrieve": "retrieve",
            "generate": "generate",
        },
    )
    workflow.add_edge("retrieve", "relevance_check")
    workflow.add_conditional_edges(
        "relevance_check",
        evidence_decision,
        {
            "generate": "generate",
            "query_rewrite": "query_rewrite",
        },
    )
    workflow.add_edge("query_rewrite", "retrieve")
    workflow.add_edge("generate", END)
    agent = workflow.compile()
