"""LLM review and offline consensus helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List

from config import get_settings
from models.request_models import SectionType
from models.signal_models import GeminiAnalysisResult

_SIGN_MAP = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}


@dataclass(frozen=True)
class ReviewDecision:
    needs_review: bool
    reason: str | None = None


def should_request_review(
    *,
    primary_result: GeminiAnalysisResult | None,
    phase1_raw_score: float,
    phase1_confidence: float,
    important_chunk: bool,
    section_type: SectionType | None,
    current_chunk: str,
    integrity_valid: bool,
    integrity_reason: str,
    primary_parse_failed: bool = False,
) -> ReviewDecision:
    """Decide whether the live path should escalate from Flash to Pro."""

    settings = get_settings()

    if primary_parse_failed:
        return ReviewDecision(True, "primary_parse_failed")

    if primary_result is None:
        return ReviewDecision(True, "primary_result_missing")

    if not integrity_valid:
        return ReviewDecision(True, f"integrity:{integrity_reason}")

    phase1_direction = _direction_from_score(phase1_raw_score)
    conflict = (
        phase1_direction != "NEUTRAL"
        and primary_result.direction != "NEUTRAL"
        and phase1_direction != primary_result.direction
    )
    if conflict and phase1_confidence >= 0.70 and primary_result.confidence >= 0.70:
        return ReviewDecision(True, "phase1_direction_conflict")

    if (
        primary_result.confidence < settings.llm_router_review_confidence_threshold
        and important_chunk
    ):
        return ReviewDecision(True, "important_low_confidence")

    if primary_result.euphemism_count >= 2 and (
        section_type == SectionType.Q_AND_A or _contains_guidance_context(current_chunk)
    ):
        return ReviewDecision(True, "euphemism_guidance_or_qa")

    return ReviewDecision(False, None)


def should_run_consensus(result: GeminiAnalysisResult, prompt_tokens: int) -> bool:
    """Offline or research-only consensus trigger."""

    settings = get_settings()
    weak_direction = abs(_SIGN_MAP.get(result.direction, 0.0) * result.magnitude) < 0.35
    low_confidence = result.confidence < settings.gemini_consensus_min_confidence
    euphemistic = result.euphemism_count >= 2
    big_prompt = prompt_tokens > settings.analysis_target_chunk_tokens
    return low_confidence or weak_direction or euphemistic or big_prompt


def aggregate_consensus(results: Iterable[GeminiAnalysisResult]) -> GeminiAnalysisResult:
    """Aggregate multiple LLM candidates into a single stable result."""

    candidates: List[GeminiAnalysisResult] = list(results)
    if not candidates:
        raise ValueError("at least one result is required for consensus")
    if len(candidates) == 1:
        return candidates[0]

    weighted_votes = {}
    rationale_map = {}
    catalyst_votes = Counter()
    euphemism_bucket = []

    for result in candidates:
        vote_weight = max(0.05, result.confidence * max(result.magnitude, 0.1))
        weighted_votes[result.direction] = weighted_votes.get(result.direction, 0.0) + vote_weight
        catalyst_votes[result.catalyst_type] += 1
        if result.direction not in rationale_map or vote_weight > rationale_map[result.direction][0]:
            rationale_map[result.direction] = (vote_weight, result.rationale, result.cot_reasoning)
        euphemism_bucket.append(result.euphemism_count)

    dominant_direction, dominant_weight = max(weighted_votes.items(), key=lambda item: item[1])
    total_weight = sum(weighted_votes.values()) or 1.0
    disagreement = round(1.0 - (dominant_weight / total_weight), 4)

    supporting = [result for result in candidates if result.direction == dominant_direction]
    avg_confidence = sum(result.confidence for result in supporting) / len(supporting)
    avg_magnitude = sum(result.magnitude for result in supporting) / len(supporting)
    _, rationale, cot_reasoning = rationale_map[dominant_direction]
    catalyst = catalyst_votes.most_common(1)[0][0]
    consensus_score = _SIGN_MAP.get(dominant_direction, 0.0) * avg_confidence * avg_magnitude

    return GeminiAnalysisResult(
        direction=dominant_direction,
        magnitude=round(avg_magnitude, 4),
        confidence=round(avg_confidence, 4),
        rationale=rationale,
        catalyst_type=catalyst,
        euphemism_count=round(sum(euphemism_bucket) / len(euphemism_bucket)),
        negative_word_ratio=max(result.negative_word_ratio for result in supporting),
        cot_reasoning=cot_reasoning,
        model_route="consensus",
        consensus_score=round(consensus_score, 4),
        disagreement_score=disagreement,
    )


def _direction_from_score(score: float) -> str:
    if score > 0.05:
        return "BULLISH"
    if score < -0.05:
        return "BEARISH"
    return "NEUTRAL"


def _contains_guidance_context(text: str) -> bool:
    normalized = (text or "").lower()
    guidance_terms = ("guidance", "outlook", "forecast", "second half", "full year")
    return any(term in normalized for term in guidance_terms)
