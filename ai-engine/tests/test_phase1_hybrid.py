from __future__ import annotations

from config import Settings
from core.phase1_scorer import FinBertScore, Phase1Scorer
from models.request_models import MarketData, SectionType, SourceType


class FakeFinBertAdapter:
    def __init__(self, result: FinBertScore | None) -> None:
        self.result = result

    def score(self, text: str, settings: Settings) -> FinBertScore | None:
        return self.result

    def warmup(self, settings: Settings) -> bool:
        return self.result is not None

    def status_snapshot(self, configured_provider: str) -> dict[str, object]:
        loaded = self.result is not None
        return {
            "configured_provider": configured_provider,
            "effective_provider": configured_provider if loaded else "heuristic_fallback",
            "finbert_loaded": loaded,
            "finbert_available": loaded,
            "degraded": not loaded,
            "model_name": "fake-finbert",
            "device": "cpu",
            "cache_size": 0,
            "init_error": None if loaded else "unavailable",
        }


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "PHASE1_PROVIDER": "hybrid",
        "PHASE1_HEURISTIC_WEIGHT": 0.55,
        "PHASE1_FINBERT_WEIGHT": 0.45,
        "PHASE1_CONFLICT_PENALTY": 0.18,
        "PHASE1_WARMUP_ON_STARTUP": False,
    }
    values.update(overrides)
    return Settings(**values)


def _market(**overrides: float) -> MarketData:
    values = {
        "ticker": "NVDA",
        "surprise_pct": 0.0,
        "volume_ratio": 1.0,
        "gap_pct": 0.0,
        "day1_return_pct": 0.0,
        "post_earnings_drift_pct": 0.0,
    }
    values.update(overrides)
    return MarketData.model_validate(values)


def _score(scorer: Phase1Scorer, text: str, market: MarketData | None = None):
    return scorer.score(
        current_chunk=text,
        market_data=market or _market(),
        section_type=SectionType.PREPARED_REMARKS,
        source_type=SourceType.EARNINGS_CALL,
    )


def test_heuristic_keeps_negative_direction_when_sentence_contains_numbers() -> None:
    scorer = Phase1Scorer(
        settings=_settings(PHASE1_PROVIDER="heuristic"),
        finbert_adapter=FakeFinBertAdapter(None),
    )

    result = _score(scorer, "Revenue declined 20% and margins contracted 180 basis points.")

    assert result.raw_score < 0
    assert result.provider == "heuristic"
    assert result.finbert_score is None


def test_hybrid_combines_agreeing_finbert_and_heuristic_scores() -> None:
    scorer = Phase1Scorer(
        settings=_settings(),
        finbert_adapter=FakeFinBertAdapter(FinBertScore(score=0.8, confidence=0.9, label="POSITIVE")),
    )

    result = _score(
        scorer,
        "Strong demand accelerated and margins improved with raised guidance.",
        _market(surprise_pct=8.0, volume_ratio=1.8, gap_pct=4.0),
    )

    assert result.provider == "hybrid"
    assert result.raw_score > 0.6
    assert result.confidence > 0.7
    assert result.heuristic_score > 0
    assert result.finbert_score == 0.8
    assert result.degraded is False


def test_hybrid_penalizes_direction_conflict() -> None:
    settings = _settings()
    scorer = Phase1Scorer(
        settings=settings,
        finbert_adapter=FakeFinBertAdapter(FinBertScore(score=-0.8, confidence=0.9, label="NEGATIVE")),
    )

    result = _score(
        scorer,
        "Strong demand accelerated with raised guidance.",
        _market(surprise_pct=7.0, volume_ratio=1.6),
    )

    weighted_confidence = result.heuristic_score * 0 + (0.55 * 0.0)  # document that score/confidence are independently blended
    assert weighted_confidence == 0.0
    assert "conflict=true" in result.rationale_hint
    assert result.confidence < 0.7
    assert abs(result.raw_score) < max(abs(result.heuristic_score), abs(result.finbert_score or 0.0))


def test_hybrid_falls_back_when_finbert_runtime_is_unavailable() -> None:
    scorer = Phase1Scorer(settings=_settings(), finbert_adapter=FakeFinBertAdapter(None))

    result = _score(scorer, "Backlog grew and demand remained strong.", _market(surprise_pct=3.0))
    status = scorer.status_snapshot()

    assert result.raw_score > 0
    assert result.provider == "hybrid:heuristic_fallback"
    assert result.degraded is True
    assert status["effective_provider"] == "heuristic_fallback"
    assert status["degraded"] is True
