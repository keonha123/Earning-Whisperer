from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from models.request_models import MarketData
    from models.signal_models import GeminiAnalysisResult, StrategyName
except ImportError:  # pragma: no cover
    from ..models.request_models import MarketData
    from ..models.signal_models import GeminiAnalysisResult, StrategyName


@dataclass(frozen=True)
class StrategyPathProfile:
    mfe_atr: float
    mae_atr: float
    base_hold_days: int


_PRIORS: dict[StrategyName, StrategyPathProfile] = {
    StrategyName.PEAD: StrategyPathProfile(mfe_atr=2.7, mae_atr=1.1, base_hold_days=2),
    StrategyName.GAP_AND_GO: StrategyPathProfile(mfe_atr=2.3, mae_atr=1.2, base_hold_days=2),
    StrategyName.GAP_FILL: StrategyPathProfile(mfe_atr=1.4, mae_atr=0.9, base_hold_days=1),
    StrategyName.REVERSAL_CATALYST: StrategyPathProfile(mfe_atr=1.5, mae_atr=1.0, base_hold_days=1),
    StrategyName.IV_CRUSH_DECAY: StrategyPathProfile(mfe_atr=1.2, mae_atr=0.8, base_hold_days=1),
    StrategyName.SHORT_SQUEEZE: StrategyPathProfile(mfe_atr=3.1, mae_atr=1.8, base_hold_days=2),
    StrategyName.WHISPER_PLAY: StrategyPathProfile(mfe_atr=2.4, mae_atr=1.2, base_hold_days=2),
    StrategyName.NEWS_BREAKOUT: StrategyPathProfile(mfe_atr=2.2, mae_atr=1.1, base_hold_days=2),
    StrategyName.MOMENTUM_CARRY: StrategyPathProfile(mfe_atr=2.9, mae_atr=1.1, base_hold_days=3),
    StrategyName.SENTIMENT_ONLY: StrategyPathProfile(mfe_atr=0.9, mae_atr=0.9, base_hold_days=1),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _percentage_points(value: float | None) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return numeric * 100.0 if abs(numeric) <= 1.0 else numeric


def estimate_mfe_mae_profile(
    *,
    strategy: StrategyName,
    score: float,
    market_data: MarketData,
    gemini_result: GeminiAnalysisResult | None,
    risk_flags: list[str],
    event_quality: float | None,
    transcript_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prior = _PRIORS.get(strategy, StrategyPathProfile(mfe_atr=1.5, mae_atr=1.0, base_hold_days=2))
    transcript_signals = transcript_signals or {}

    mfe_mult = 1.0
    mae_mult = 1.0
    reasons: list[str] = []

    if score >= 0.75:
        mfe_mult += 0.10
        reasons.append("high_strategy_score_supports_larger_favorable_excursion")
    elif score <= 0.45:
        mfe_mult -= 0.12
        mae_mult += 0.08
        reasons.append("weak_strategy_score_reduces_expected_path_quality")

    confidence = gemini_result.confidence if gemini_result is not None else 0.65
    if confidence >= 0.82:
        mfe_mult += 0.08
        reasons.append("high_model_confidence_supports_longer_path")
    elif confidence <= 0.58:
        mfe_mult -= 0.08
        mae_mult += 0.06
        reasons.append("low_model_confidence_increases_adverse_excursion_risk")

    if market_data.volume_ratio >= 2.2:
        mfe_mult += 0.08
        reasons.append("volume_confirmation_improves_mfe_capture_probability")
    elif market_data.volume_ratio < 1.2:
        mfe_mult -= 0.06
        mae_mult += 0.06
        reasons.append("weak_volume_confirmation_raises_mae_risk")

    if event_quality is not None:
        if event_quality >= 0.72:
            mfe_mult += 0.10
            reasons.append("high_event_quality_improves_mfe_mae_ratio")
        elif event_quality < 0.56:
            mfe_mult -= 0.10
            mae_mult += 0.08
            reasons.append("low_event_quality_reduces_expected_follow_through")

    if market_data.vix >= 24:
        mae_mult += 0.12
        reasons.append("high_vix_expands_adverse_path_dispersion")
    if _percentage_points(market_data.relative_strength_20d) >= 6:
        mfe_mult += 0.06
        reasons.append("relative_strength_supports_path_extension")
    if market_data.rsi_14 is not None and market_data.rsi_14 >= 76:
        mae_mult += 0.08
        reasons.append("overextended_rsi_increases_pullback_depth")

    if "qa_evasive_answer" in risk_flags or float(transcript_signals.get("evasion_score", 0.0) or 0.0) >= 0.58:
        mae_mult += 0.07
        reasons.append("evasive_qna_increases_path_fragility")
    if "management_contradiction_risk" in risk_flags or float(transcript_signals.get("contradiction_penalty", 0.0) or 0.0) <= -0.14:
        mae_mult += 0.10
        mfe_mult -= 0.05
        reasons.append("management_contradiction_compresses_mfe_mae_ratio")
    if float(transcript_signals.get("acoustic_stress", 0.0) or 0.0) >= 0.08:
        mae_mult += 0.05
        reasons.append("acoustic_stress_increases_exit_sensitivity")

    for topic in (transcript_signals.get("topic_deltas") or {}):
        pass
    topic_deltas = transcript_signals.get("topic_deltas") or {}
    if isinstance(topic_deltas, dict):
        guidance = float(topic_deltas.get("guidance", 0.0) or 0.0)
        demand = float(topic_deltas.get("demand", 0.0) or 0.0)
        margin = float(topic_deltas.get("margin", 0.0) or 0.0)
        capex = float(topic_deltas.get("capex", 0.0) or 0.0)
        if guidance >= 0.18:
            mfe_mult += 0.08
            reasons.append("guidance_shifted_upward")
        elif guidance <= -0.18:
            mfe_mult -= 0.08
            mae_mult += 0.05
            reasons.append("guidance_shifted_downward")
        if demand >= 0.16:
            mfe_mult += 0.05
            reasons.append("demand_mentions_improved")
        elif demand <= -0.16:
            mfe_mult -= 0.05
            mae_mult += 0.04
            reasons.append("demand_mentions_softened")
        if margin >= 0.14:
            mfe_mult += 0.04
            reasons.append("margin_commentary_improved")
        elif margin <= -0.14:
            mfe_mult -= 0.05
            mae_mult += 0.05
            reasons.append("margin_commentary_weakened")
        if capex >= 0.16 and demand >= 0.08:
            mfe_mult += 0.03
            reasons.append("capex_increase_looked_growth_supportive")
        elif capex >= 0.16 and margin <= -0.10:
            mae_mult += 0.04
            reasons.append("capex_increase_looked_margin_dilutive")

    mfe_atr = prior.mfe_atr * _clamp(mfe_mult, 0.65, 1.45)
    mae_atr = prior.mae_atr * _clamp(mae_mult, 0.75, 1.55)
    mfe_mae_ratio = mfe_atr / max(mae_atr, 0.35)

    hold_bias = 0
    if mfe_mae_ratio >= 2.15:
        hold_bias = 1
    elif mfe_mae_ratio <= 1.25:
        hold_bias = -1

    return {
        "prior_mfe_atr": round(prior.mfe_atr, 3),
        "prior_mae_atr": round(prior.mae_atr, 3),
        "expected_mfe_atr": round(mfe_atr, 3),
        "expected_mae_atr": round(mae_atr, 3),
        "expected_mfe_mae_ratio": round(mfe_mae_ratio, 3),
        "hold_bias": hold_bias,
        "reasons": reasons[:8],
    }
