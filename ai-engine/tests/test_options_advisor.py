from __future__ import annotations

from core.options_advisor import build_options_advice
from models.request_models import MarketData
from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


def test_options_advisor_emits_zero_dte_overlay_when_flow_is_aligned() -> None:
    market_data = MarketData.model_validate(
        {
            "ticker": "NVDA",
            "current_price": 100.0,
            "current_iv": 0.62,
            "realized_vol_10d": 0.41,
            "zero_dte_available": True,
            "zero_dte_gamma_pressure": 0.38,
            "zero_dte_put_call_volume_ratio": 0.72,
            "zero_dte_atm_straddle_pct": 2.4,
        }
    )
    decision = StrategyDecision(
        strategy=StrategyName.GAP_AND_GO,
        score=0.81,
        hold_days=3,
        rationale="continuation",
    )
    analysis = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.8,
        confidence=0.84,
        rationale="aligned setup",
        catalyst_type="EARNINGS_BEAT",
    )

    advice = build_options_advice(market_data, decision, analysis)

    assert advice is not None
    assert advice["zero_dte_overlay"]["enabled"] is True
    assert advice["zero_dte_overlay"]["preferred_structure"] == "0dte_call_vertical_small"


def test_options_advisor_marks_zero_dte_as_avoid_when_flow_conflicts() -> None:
    market_data = MarketData.model_validate(
        {
            "ticker": "TSLA",
            "current_price": 100.0,
            "current_iv": 0.58,
            "realized_vol_10d": 0.44,
            "zero_dte_available": True,
            "zero_dte_gamma_pressure": -0.30,
            "zero_dte_put_call_volume_ratio": 1.35,
            "zero_dte_atm_straddle_pct": 3.1,
        }
    )
    decision = StrategyDecision(
        strategy=StrategyName.GAP_AND_GO,
        score=0.77,
        hold_days=2,
        rationale="continuation",
    )
    analysis = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.72,
        confidence=0.79,
        rationale="conflicted setup",
        catalyst_type="GUIDANCE_UP",
    )

    advice = build_options_advice(market_data, decision, analysis)

    assert advice is not None
    assert advice["zero_dte_overlay"]["enabled"] is False
    assert advice["zero_dte_overlay"]["stance"] == "avoid"
