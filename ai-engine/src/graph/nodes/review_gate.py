"""Primary-result review gate."""

from __future__ import annotations

from core.gemini_client import gemini_client
from core.integrity_validator import validate_integrity
from core.llm_consistency import should_request_review
from ..state import AgentState


async def review_gate(state: AgentState) -> AgentState:
    try:
        primary_result = gemini_client.parse_response_text(state["primary_result_text"])
    except Exception:
        return {
            **state,
            "primary_parse_failed": True,
            "needs_review": True,
            "review_reason": "primary_parse_failed",
        }

    integrity_valid, integrity_reason = validate_integrity(
        state["current_chunk"],
        primary_result,
    )
    review = should_request_review(
        primary_result=primary_result,
        phase1_raw_score=state.get("phase1_raw_score", 0.0),
        phase1_confidence=state.get("phase1_confidence", 0.0),
        important_chunk=state.get("important_chunk", False),
        section_type=state.get("section_type"),
        current_chunk=state["current_chunk"],
        integrity_valid=integrity_valid,
        integrity_reason=integrity_reason,
        primary_parse_failed=False,
    )

    next_state: AgentState = {
        **state,
        "parsed_primary_result": primary_result,
        "needs_review": review.needs_review,
        "review_reason": review.reason or "",
    }
    if not review.needs_review:
        next_state["result"] = primary_result
    return next_state
