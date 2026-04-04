from __future__ import annotations

from ..core.contract_adapter import to_backend_redis_signal
from ..core.phase1_scorer import _score_from_probabilities, blend_raw_scores, phase1_scorer
from ..models.signal_models import TradingSignalV3


def test_phase1_scorer_detects_positive_language():
    result = phase1_scorer.analyze_text(
        "We delivered record growth, strong demand, and improved profitability."
    )

    assert result.raw_score > 0.0
    assert result.provider in {"finbert_phase1", "lexical_phase1"}


def test_phase1_scorer_detects_negative_language():
    result = phase1_scorer.analyze_text(
        "We missed expectations, delayed the launch, and faced margin pressure."
    )

    assert result.raw_score < 0.0


def test_blend_raw_scores_prefers_phase1_signal_when_llm_disagrees():
    blended = blend_raw_scores(phase1_score=-0.8, llm_score=0.3, llm_available=True)
    assert blended < 0.0
    assert abs(blended) > 0.5


def test_finbert_probability_mapping_to_raw_score():
    raw_score, confidence = _score_from_probabilities(
        [0.80, 0.10, 0.10],
        {0: "positive", 1: "negative", 2: "neutral"},
    )

    assert raw_score == 0.7
    assert confidence == 0.8


def test_contract_adapter_emits_backend_minimal_payload():
    signal = TradingSignalV3(
        ticker="NVDA",
        raw_score=0.81234,
        rationale="Management reaffirmed demand strength.",
        text_chunk="We continue to see strong AI demand.",
        timestamp=1732143600,
        composite_score=0.9,
        trade_approved=True,
    )

    contract = to_backend_redis_signal(signal, is_session_end=False)

    assert contract.model_dump() == {
        "ticker": "NVDA",
        "raw_score": 0.8123,
        "rationale": "Management reaffirmed demand strength.",
        "text_chunk": "We continue to see strong AI demand.",
        "timestamp": 1732143600,
        "is_session_end": False,
    }
