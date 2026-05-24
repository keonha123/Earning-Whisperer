from __future__ import annotations

from dataclasses import dataclass

try:
    from models.signal_models import GeminiAnalysisResult
except ImportError:  # pragma: no cover
    from ..models.signal_models import GeminiAnalysisResult


@dataclass(slots=True)
class ReviewDecision:
    needs_review: bool
    reason: str = ""


def should_request_review(
    primary_result: GeminiAnalysisResult | None = None,
    phase1_raw_score: float | None = None,
    phase1_confidence: float | None = None,
    important_chunk: bool = False,
    section_type=None,
    current_chunk: str = "",
    integrity_valid: bool = True,
    integrity_reason: str = "",
    primary_parse_failed: bool = False,
    disagreement_threshold: float = 0.35,
) -> ReviewDecision:
    result = primary_result
    if result is None:
        return ReviewDecision(True, "missing_primary_result")
    if primary_parse_failed:
        return ReviewDecision(True, "parse_failed")
    if not integrity_valid:
        return ReviewDecision(True, integrity_reason or "integrity_failed")
    if result.review_triggered or result.review_reason:
        return ReviewDecision(True, result.review_reason or "review_triggered")
    if important_chunk and result.confidence < 0.55:
        return ReviewDecision(True, "low_confidence_important_chunk")
    if (result.disagreement_score or 0.0) >= disagreement_threshold:
        return ReviewDecision(True, "self_consistency_disagreement")
    phase1_direction = 1 if (phase1_raw_score or 0.0) > 0 else -1 if (phase1_raw_score or 0.0) < 0 else 0
    llm_direction = 1 if result.direction.upper() in {"UP", "BUY", "BULLISH", "POSITIVE"} else -1 if result.direction.upper() in {"DOWN", "SELL", "BEARISH", "NEGATIVE"} else 0
    if phase1_confidence is not None and phase1_confidence >= 0.75 and phase1_direction != 0 and llm_direction != 0 and phase1_direction != llm_direction:
        return ReviewDecision(True, "phase1_direction_conflict")
    if "headwind" in current_chunk.lower() and llm_direction > 0 and important_chunk:
        return ReviewDecision(True, "text_signal_conflict")
    return ReviewDecision(False, "")
