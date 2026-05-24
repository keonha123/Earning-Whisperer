from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FinalizedResult:
    direction: str
    magnitude: float
    confidence: float
    rationale: str
    catalyst_type: str
    model_route: str = "fallback"
    strategy: str = "SENTIMENT_ONLY"
    review_triggered: bool = False
    hold_days: int = 1
    risk_flags: list[str] = field(default_factory=list)


async def parse_and_finalize(state: dict[str, Any]) -> dict[str, FinalizedResult]:
    parsed = state.get("parsed_result") or {}
    if parsed:
        return {
            "result": FinalizedResult(
                direction=parsed.get("direction", "NEUTRAL"),
                magnitude=parsed.get("magnitude", 0.0),
                confidence=parsed.get("confidence", 0.0),
                rationale=parsed.get("rationale", "Parsed result"),
                catalyst_type=parsed.get("catalyst_type", "UNCLASSIFIED"),
                model_route=parsed.get("model_route", "direct"),
                strategy=parsed.get("strategy", "SENTIMENT_ONLY"),
                review_triggered=parsed.get("review_triggered", False),
                hold_days=parsed.get("hold_days", 1),
                risk_flags=parsed.get("risk_flags", []),
            )
        }

    raw_response = state.get("raw_response", "")
    analysis = state.get("analysis") or {}
    primary_model = state.get("primary_model", "unknown")
    return {
        "result": FinalizedResult(
            direction=analysis.get("direction", "NEUTRAL"),
            magnitude=analysis.get("magnitude", 0.0),
            confidence=analysis.get("confidence", 0.0),
            rationale=raw_response or analysis.get("rationale", "Fallback analysis generated because parsing failed"),
            catalyst_type=analysis.get("catalyst_type", "UNCLASSIFIED"),
            model_route=f"{primary_model}->fallback",
            strategy="ERROR_FALLBACK",
        )
    }
