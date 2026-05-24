from __future__ import annotations

from dataclasses import dataclass, field

try:
    from models.request_models import SourceType
    from models.signal_models import GeminiAnalysisResult
except ImportError:  # pragma: no cover
    from ..models.request_models import SourceType
    from ..models.signal_models import GeminiAnalysisResult


@dataclass(slots=True)
class AnalysisProvenance:
    quality_grade: str
    reliability_flags: list[str] = field(default_factory=list)
    source_mix: dict[str, int] = field(default_factory=dict)
    evidence_count: int = 0


def build_analysis_provenance(
    *,
    source_type: SourceType,
    section_type: str,
    context_chunk_count: int,
    has_market_data: bool,
    llm_available: bool,
    result: GeminiAnalysisResult,
) -> AnalysisProvenance:
    flags: list[str] = []
    score = 0.0

    source_mix = {source_type.value: 1, section_type: 1}
    evidence_count = 2

    if context_chunk_count > 0:
        source_mix["ROLLING_CONTEXT"] = context_chunk_count
        evidence_count += context_chunk_count
        score += 0.15
    if has_market_data:
        source_mix["MARKET_DATA"] = 1
        evidence_count += 1
        score += 0.20
    if llm_available:
        score += 0.10
    else:
        flags.append("LLM_FALLBACK")
    if "fallback" in (result.model_route or "").lower():
        if "LLM_FALLBACK" not in flags:
            flags.append("LLM_FALLBACK")
        score -= 0.30
    score += max(0.0, min(0.35, result.confidence * 0.35))
    score += max(0.0, min(0.15, abs(result.magnitude) * 0.15))
    if result.confidence < 0.5:
        flags.append("LOW_CONFIDENCE")
        score -= 0.20
    if (result.disagreement_score or 0.0) >= 0.35:
        flags.append("HIGH_DISAGREEMENT")
        score -= 0.20
    if result.euphemism_count > 0:
        score -= 0.05

    if score >= 0.65:
        grade = "A"
    elif score >= 0.45:
        grade = "B"
    elif score >= 0.25:
        grade = "C"
    elif score >= 0.10:
        grade = "D"
    else:
        grade = "E"

    return AnalysisProvenance(quality_grade=grade, reliability_flags=flags, source_mix=source_mix, evidence_count=evidence_count)
