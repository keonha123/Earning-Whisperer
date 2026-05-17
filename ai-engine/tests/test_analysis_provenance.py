from __future__ import annotations

try:
    from ..core.analysis_provenance import build_analysis_provenance
    from ..models.request_models import SourceType
    from ..models.signal_models import GeminiAnalysisResult
except ImportError:  # pragma: no cover - direct pytest execution from ai-engine/
    from core.analysis_provenance import build_analysis_provenance
    from models.request_models import SourceType
    from models.signal_models import GeminiAnalysisResult


def test_build_analysis_provenance_marks_fallback_and_low_confidence():
    result = GeminiAnalysisResult(
        direction="NEUTRAL",
        magnitude=0.1,
        confidence=0.2,
        rationale="fallback",
        catalyst_type="MACRO_COMMENTARY",
        euphemism_count=0,
        model_route="gemini-2.5-flash-preview->fallback",
        disagreement_score=0.6,
    )

    provenance = build_analysis_provenance(
        source_type=SourceType.EARNINGS_CALL,
        section_type="Q_AND_A",
        context_chunk_count=0,
        has_market_data=False,
        llm_available=False,
        result=result,
    )

    assert provenance.quality_grade in {"D", "E"}
    assert "LLM_FALLBACK" in provenance.reliability_flags
    assert "LOW_CONFIDENCE" in provenance.reliability_flags
    assert "HIGH_DISAGREEMENT" in provenance.reliability_flags
    assert provenance.source_mix["Q_AND_A"] == 1
    assert provenance.evidence_count >= 1


def test_build_analysis_provenance_scores_strong_supported_result_higher():
    result = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.82,
        confidence=0.91,
        rationale="strong evidence",
        catalyst_type="GUIDANCE_UP",
        euphemism_count=0,
        model_route="gemini-2.5-flash-preview->gemini-2.5-pro",
        review_reason="important_low_confidence",
        disagreement_score=0.08,
    )

    provenance = build_analysis_provenance(
        source_type=SourceType.NEWS,
        section_type="OTHER",
        context_chunk_count=3,
        has_market_data=True,
        llm_available=True,
        result=result,
    )

    assert provenance.quality_grade in {"A", "B"}
    assert provenance.reliability_flags == []
    assert provenance.source_mix["NEWS"] == 1
    assert provenance.source_mix["ROLLING_CONTEXT"] == 3
    assert provenance.source_mix["MARKET_DATA"] == 1
    assert provenance.evidence_count == 6
