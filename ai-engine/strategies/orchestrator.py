from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from config import get_settings
    from core.event_quality import score_event_quality
    from core.mfe_mae_tuner import estimate_mfe_mae_profile
    from core.strategy_track_rules import (
        nasdaq100_aggressive_rotation_allowed,
        nasdaq100_aggressive_sector_blocked,
        nasdaq100_aggressive_strategy_allowed,
        nasdaq100_conservative_gap_extended,
        nasdaq100_conservative_high_vol_news_blocked,
        nasdaq100_conservative_quality_reversal_allowed,
        nasdaq100_conservative_sector_allowed,
        sp500_aggressive_sector_blocked,
        sp500_aggressive_strategy_allowed,
        sp500_conservative_gap_sector_blocked,
    )
    from core.universe_profiles import (
        RiskStyleName,
        UniverseName,
        compose_universe_profile,
        get_allowed_strategies,
        resolve_universe_profile,
    )
    from models.request_models import MarketData, SectionType
    from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from ..core.event_quality import score_event_quality
    from ..core.mfe_mae_tuner import estimate_mfe_mae_profile
    from ..core.strategy_track_rules import (
        nasdaq100_aggressive_rotation_allowed,
        nasdaq100_aggressive_sector_blocked,
        nasdaq100_aggressive_strategy_allowed,
        nasdaq100_conservative_gap_extended,
        nasdaq100_conservative_high_vol_news_blocked,
        nasdaq100_conservative_quality_reversal_allowed,
        nasdaq100_conservative_sector_allowed,
        sp500_aggressive_sector_blocked,
        sp500_aggressive_strategy_allowed,
        sp500_conservative_gap_sector_blocked,
    )
    from ..core.universe_profiles import (
        RiskStyleName,
        UniverseName,
        compose_universe_profile,
        get_allowed_strategies,
        resolve_universe_profile,
    )
    from ..models.request_models import MarketData, SectionType
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


@dataclass(slots=True)
class StrategyCandidate:
    strategy: StrategyName
    score: float
    rationale: str


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _scaled_abs(value: float, scale: float) -> float:
    return _clamp(abs(value) / scale)


def _percentage_points(value: float | None) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return numeric * 100.0 if abs(numeric) <= 1.0 else numeric


def _classify_regime(market_data: MarketData) -> str:
    relative_strength_points = _percentage_points(market_data.relative_strength_20d)
    if float(market_data.vix or 0.0) >= 25.0:
        return "high_vol"
    if relative_strength_points < -5.0:
        return "risk_off"
    if relative_strength_points > 8.0:
        return "trend_up"
    return "normal"


def _direction_sign(analysis: GeminiAnalysisResult | None) -> float:
    if analysis is None:
        return 0.0
    if analysis.direction == "BULLISH":
        return 1.0
    if analysis.direction == "BEARISH":
        return -1.0
    return 0.0


def _analysis_value(analysis: GeminiAnalysisResult | None, key: str, default: float = 0.0) -> float:
    if analysis is None:
        return default
    value = getattr(analysis, key, default)
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _metadata_dict(analysis: GeminiAnalysisResult | None) -> dict[str, Any]:
    metadata = analysis.metadata if (analysis is not None and isinstance(analysis.metadata, dict)) else {}
    return metadata if isinstance(metadata, dict) else {}


def _transcript_signals(analysis: GeminiAnalysisResult | None) -> dict[str, Any]:
    payload = _metadata_dict(analysis).get("transcript_signals")
    return payload if isinstance(payload, dict) else {}


def _topic_delta_value(transcript_signals: dict[str, Any], topic: str) -> float:
    topic_deltas = transcript_signals.get("topic_deltas") or {}
    if not isinstance(topic_deltas, dict):
        return 0.0
    value = topic_deltas.get(topic, 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _transcript_continuation_score(analysis: GeminiAnalysisResult | None) -> float:
    transcript_signals = _transcript_signals(analysis)
    if not transcript_signals:
        return 0.0

    guidance = _topic_delta_value(transcript_signals, "guidance")
    demand = _topic_delta_value(transcript_signals, "demand")
    margin = _topic_delta_value(transcript_signals, "margin")
    capex = _topic_delta_value(transcript_signals, "capex")
    evasion = float(transcript_signals.get("evasion_score", 0.0) or 0.0)
    contradiction = float(transcript_signals.get("contradiction_penalty", 0.0) or 0.0)
    stress = float(transcript_signals.get("acoustic_stress", 0.0) or 0.0)
    negative_word_ratio = _analysis_value(analysis, "negative_word_ratio", 0.0)

    score = (
        guidance * 0.40
        + demand * 0.28
        + margin * 0.20
        + min(capex, 0.20) * 0.08
        - evasion * 0.28
        + min(0.0, contradiction) * 0.55
        - stress * 0.14
        - negative_word_ratio * 0.12
    )
    return _clamp(score, -1.0, 1.0)


def _implied_gap_overshoot(market_data: MarketData) -> float:
    implied_move = getattr(market_data, "implied_move_pct", None)
    gap_pct = abs(float(market_data.gap_pct or 0.0))
    if implied_move is None:
        return 0.0
    try:
        implied_move = abs(float(implied_move))
    except (TypeError, ValueError):
        return 0.0
    if implied_move < 0.5:
        return 0.0
    overshoot = (gap_pct / implied_move) - 1.0
    return max(0.0, overshoot)


def _benchmark_support(market_data: MarketData) -> float:
    scores: list[float] = []
    if market_data.spy_relative_strength_20d is not None:
        scores.append(_clamp((float(market_data.spy_relative_strength_20d) + 8.0) / 16.0))
    if market_data.qqq_relative_strength_20d is not None:
        scores.append(_clamp((float(market_data.qqq_relative_strength_20d) + 8.0) / 16.0))
    return sum(scores) / len(scores) if scores else 0.5


def _technical_trend_support(market_data: MarketData) -> float:
    scores: list[float] = []
    if market_data.current_price and market_data.ma200:
        scores.append(1.0 if float(market_data.current_price) > float(market_data.ma200) else 0.0)
    if market_data.ma_stack_bullish is not None:
        scores.append(1.0 if market_data.ma_stack_bullish else 0.0)
    if market_data.ichimoku_weekly_cloud_score is not None:
        scores.append(_clamp((float(market_data.ichimoku_weekly_cloud_score) + 1.0) / 2.0))
    return sum(scores) / len(scores) if scores else 0.5


def _fundamental_support(market_data: MarketData) -> float:
    scores: list[float] = []
    if market_data.revenue_growth_yoy is not None:
        scores.append(_clamp((float(market_data.revenue_growth_yoy) + 5.0) / 25.0))
    if market_data.earnings_growth_yoy is not None:
        scores.append(_clamp((float(market_data.earnings_growth_yoy) + 5.0) / 30.0))
    if market_data.gross_margin is not None:
        scores.append(_clamp(float(market_data.gross_margin) / 60.0))
    if market_data.operating_margin is not None:
        scores.append(_clamp((float(market_data.operating_margin) + 5.0) / 30.0))
    if market_data.fcf_margin is not None:
        scores.append(_clamp((float(market_data.fcf_margin) + 5.0) / 30.0))
    if market_data.debt_to_equity is not None:
        scores.append(1.0 - _clamp(float(market_data.debt_to_equity) / 250.0))
    if market_data.current_ratio is not None:
        scores.append(_clamp(float(market_data.current_ratio) / 2.5))
    return sum(scores) / len(scores) if scores else 0.5


def _exhaustion_score(market_data: MarketData) -> float:
    scores: list[float] = []
    if market_data.rsi_14 is not None:
        scores.append(_clamp((float(market_data.rsi_14) - 55.0) / 25.0))
    if market_data.stochastic_k is not None:
        scores.append(_clamp((float(market_data.stochastic_k) - 55.0) / 30.0))
    if market_data.bb_position is not None:
        scores.append(_clamp((float(market_data.bb_position) - 0.55) / 0.40))
    return sum(scores) / len(scores) if scores else 0.0


def _options_flow_support(market_data: MarketData, *, bullish: bool) -> float:
    if not market_data.zero_dte_available:
        return 0.5

    scores: list[float] = []
    if market_data.zero_dte_gamma_pressure is not None:
        gamma = float(market_data.zero_dte_gamma_pressure)
        scores.append(_clamp((gamma + 1.0) / 2.0) if bullish else _clamp((1.0 - gamma) / 2.0))
    if market_data.zero_dte_put_call_volume_ratio is not None:
        ratio = float(market_data.zero_dte_put_call_volume_ratio)
        if bullish:
            scores.append(_clamp((1.35 - ratio) / 0.85))
        else:
            scores.append(_clamp((ratio - 0.75) / 0.85))
    return sum(scores) / len(scores) if scores else 0.5


def _base_horizon_days(strategy: StrategyName) -> int:
    settings = get_settings()
    horizon_map = {
        StrategyName.IV_CRUSH_DECAY: settings.iv_crush_horizon_days,
        StrategyName.REVERSAL_CATALYST: settings.reversal_catalyst_horizon_days,
        StrategyName.PEAD: settings.pead_horizon_days,
        StrategyName.GAP_AND_GO: settings.gap_and_go_horizon_days,
        StrategyName.GAP_FILL: settings.gap_fill_horizon_days,
        StrategyName.WHISPER_PLAY: settings.whisper_play_horizon_days,
        StrategyName.SHORT_SQUEEZE: settings.short_squeeze_horizon_days,
        StrategyName.NEWS_BREAKOUT: settings.news_breakout_horizon_days,
        StrategyName.SENTIMENT_ONLY: 1,
    }
    return horizon_map.get(strategy, settings.momentum_carry_horizon_days)


def _event_quality_for_strategy(strategy: StrategyName, metadata: dict[str, object]) -> float | None:
    event_quality = metadata.get("event_quality")
    if not isinstance(event_quality, dict):
        return None
    key_map = {
        StrategyName.GAP_AND_GO: "gap_and_go",
        StrategyName.PEAD: "pead",
        StrategyName.NEWS_BREAKOUT: "news_breakout",
    }
    key = key_map.get(strategy)
    if key is None:
        return None
    payload = event_quality.get(key)
    if isinstance(payload, dict) and payload.get("total") is not None:
        return float(payload["total"])
    return None


def _estimated_execution_cost_pct(market_data: MarketData, settings) -> float:
    spread_bps = market_data.bid_ask_spread_bps
    if spread_bps is None:
        spread_bps = settings.slippage_bps_default
    return (
        float(settings.backtest_round_trip_cost_pct)
        + float(spread_bps or 0.0) / 100.0
        + float(settings.execution_latency_bps_default) / 100.0
    )


def _resolve_strategy_profile(
    *,
    market_data: MarketData,
    universe_profile: str | None,
    risk_style: str | None,
):
    if universe_profile:
        return compose_universe_profile(str(universe_profile).strip().upper(), risk_style)
    base = resolve_universe_profile(market_data.ticker)
    default_style = risk_style
    if default_style is None:
        default_style = RiskStyleName.CONSERVATIVE.value if base.name in {UniverseName.NASDAQ100, UniverseName.SP500} else RiskStyleName.BALANCED.value
    return compose_universe_profile(base.name.value, default_style)


def _fallback_candidate(
    *,
    candidates: list[StrategyCandidate],
    current: StrategyCandidate,
    preferred: tuple[StrategyName, ...],
    rationale: str,
) -> StrategyCandidate:
    for strategy in preferred:
        replacement = next((item for item in candidates if item.strategy == strategy and item.strategy != current.strategy), None)
        if replacement is not None:
            return replacement
    for replacement in candidates:
        if replacement.strategy != current.strategy:
            return replacement
    return StrategyCandidate(StrategyName.SENTIMENT_ONLY, min(current.score, 0.35), rationale)


def _tune_hold_days(
    *,
    base_hold_days: int,
    strategy: StrategyName,
    score: float,
    market_data: MarketData,
    gemini_result: GeminiAnalysisResult | None,
    risk_flags: list[str],
    metadata: dict[str, object],
) -> tuple[int, dict[str, object]]:
    hold_days = base_hold_days
    adjustments: list[dict[str, object]] = []
    strategy_event_quality = _event_quality_for_strategy(strategy, metadata)
    transcript_signals = _transcript_signals(gemini_result)
    mfe_mae_profile = estimate_mfe_mae_profile(
        strategy=strategy,
        score=score,
        market_data=market_data,
        gemini_result=gemini_result,
        risk_flags=risk_flags,
        event_quality=strategy_event_quality,
        transcript_signals=transcript_signals,
    )

    def add_adjustment(reason: str, delta: int = 0, *, hard_set: int | None = None) -> None:
        nonlocal hold_days
        before = hold_days
        if hard_set is not None:
            hold_days = hard_set
        else:
            hold_days += delta
        if hold_days != before:
            adjustments.append({"reason": reason, "before": before, "after": hold_days})

    continuation = strategy in {
        StrategyName.PEAD,
        StrategyName.GAP_AND_GO,
        StrategyName.WHISPER_PLAY,
        StrategyName.SHORT_SQUEEZE,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
    }
    mean_reversion = strategy in {StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST}

    if continuation and score >= 0.74 and market_data.volume_ratio >= 2.0:
        add_adjustment("score_and_volume_confirmation_strong", delta=1)
    relative_strength_points = _percentage_points(market_data.relative_strength_20d)

    if strategy == StrategyName.PEAD and market_data.post_earnings_drift_pct >= 3.0 and relative_strength_points >= 5.0:
        add_adjustment("drift_and_relative_strength_support_follow_through", delta=1)
    if strategy == StrategyName.NEWS_BREAKOUT and market_data.hours_since_news is not None and market_data.hours_since_news <= 8 and market_data.volume_ratio >= 1.8:
        add_adjustment("fresh_news_with_fast_volume_confirmation", delta=1)
    if strategy == StrategyName.SHORT_SQUEEZE and market_data.float_rotation >= 1.0 and market_data.volume_ratio >= 2.5:
        add_adjustment("squeeze_rotation_is_still_active", delta=1)

    if "thin_confirmation" in risk_flags:
        add_adjustment("thin_confirmation_shortens_holding_window", delta=-1)
    if "high_vix" in risk_flags:
        add_adjustment("high_vix_calls_for_faster_exit", delta=-1)
    if "stale_catalyst" in risk_flags:
        add_adjustment("stale_catalyst_reduces_follow_through_window", delta=-1)
    if "overextended_rsi" in risk_flags and continuation:
        add_adjustment("overextended_rsi_increases_chase_risk", delta=-1)
    if "stacked_overbought" in risk_flags and continuation:
        add_adjustment("stacked_overbought_shortens_holding_window", delta=-1)
    if "below_ma200" in risk_flags and continuation:
        add_adjustment("below_ma200_reduces_follow_through_window", delta=-1)
    if "zero_dte_flow_opposition" in risk_flags and continuation:
        add_adjustment("same_day_options_flow_conflicted_with_signal", delta=-1)
    if "gap_overshot_implied_move" in risk_flags and continuation:
        add_adjustment("gap_exceeded_implied_move_so_chase_window_is_shorter", delta=-1)
    if "overshoot_without_transcript_confirmation" in risk_flags and continuation:
        add_adjustment("overshoot_lacked_transcript_confirmation", delta=-1)
    if gemini_result is not None and gemini_result.confidence < 0.62:
        add_adjustment("low_model_confidence_reduces_hold_period", delta=-1)
    if strategy_event_quality is not None and strategy_event_quality < 0.58:
        add_adjustment("subpar_event_quality_requires_quicker_risk_reduction", delta=-1)

    if float(transcript_signals.get("evasion_score", 0.0) or 0.0) >= 0.58 and continuation:
        add_adjustment("evasive_qna_reduces_continuation_confidence", delta=-1)
    if float(transcript_signals.get("contradiction_penalty", 0.0) or 0.0) <= -0.14:
        add_adjustment("contradiction_risk_requires_faster_exit", delta=-1)
    if float(transcript_signals.get("acoustic_stress", 0.0) or 0.0) >= 0.08:
        add_adjustment("acoustic_stress_shortens_holding_window", delta=-1)

    if mfe_mae_profile.get("hold_bias", 0) >= 1:
        add_adjustment("favorable_mfe_mae_ratio_extends_hold", delta=1)
    elif mfe_mae_profile.get("hold_bias", 0) <= -1:
        add_adjustment("unfavorable_mfe_mae_ratio_shortens_hold", delta=-1)

    if "near_earnings" in risk_flags:
        add_adjustment("next_earnings_is_too_close", hard_set=min(hold_days, 2))
    if mean_reversion:
        add_adjustment("mean_reversion_setups_should_not_overstay", hard_set=min(hold_days, 2))
    if strategy == StrategyName.IV_CRUSH_DECAY:
        add_adjustment("volatility_decay_is_usually_front_loaded", hard_set=min(hold_days, 2))
    if strategy == StrategyName.NEWS_BREAKOUT and "stale_catalyst" in risk_flags:
        add_adjustment("stale_news_breakout_becomes_intraday_or_one_day_only", hard_set=1)

    hold_days = max(1, min(hold_days, base_hold_days + 2))
    tuning = {
        "base_hold_days": base_hold_days,
        "final_hold_days": hold_days,
        "adjustments": adjustments,
        "event_quality_for_selected_strategy": strategy_event_quality,
        "mfe_mae_profile": mfe_mae_profile,
    }
    return hold_days, tuning


def _apply_profile_hold_floor(
    *,
    hold_days: int,
    strategy: StrategyName,
    profile: Any,
    regime: str,
    event_quality: float | None,
    market_data: MarketData,
    risk_flags: list[str],
    hold_tuning: dict[str, object],
) -> int:
    continuation = strategy in {
        StrategyName.PEAD,
        StrategyName.GAP_AND_GO,
        StrategyName.WHISPER_PLAY,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
        StrategyName.SHORT_SQUEEZE,
    }
    if not continuation:
        return hold_days

    blocker_flags = {
        "thin_confirmation",
        "stale_catalyst",
        "continuation_gate_failed",
        "trend_up_confirmation_gap",
        "gap_overshot_implied_move",
        "overshoot_without_transcript_confirmation",
        "sp500_pead_quality_gate_failed",
    }
    if any(flag in blocker_flags for flag in risk_flags):
        hold_tuning["profile_hold_floor"] = None
        hold_tuning["final_hold_days"] = hold_days
        return hold_days

    minimum_hold = 0
    quality = float(event_quality or 0.0)
    volume_ratio = float(market_data.volume_ratio or 0.0)

    if profile.risk_style_name == RiskStyleName.CONSERVATIVE:
        if regime == "trend_up" and quality >= 0.60 and volume_ratio >= 1.9:
            minimum_hold = 4
        elif quality >= 0.62 and volume_ratio >= 1.7:
            minimum_hold = 3
    elif profile.risk_style_name == RiskStyleName.AGGRESSIVE:
        if regime == "trend_up" and quality >= 0.58 and volume_ratio >= 1.8:
            minimum_hold = 4
        elif quality >= 0.58 and volume_ratio >= 1.6:
            minimum_hold = 3

    if profile.name == UniverseName.SP500 and strategy == StrategyName.PEAD and quality >= 0.72 and volume_ratio >= 2.2:
        minimum_hold = max(minimum_hold, 5)

    if minimum_hold > hold_days:
        adjustments = hold_tuning.setdefault("adjustments", [])
        if isinstance(adjustments, list):
            adjustments.append(
                {
                    "reason": f"profile_hold_floor_{minimum_hold}d",
                    "before": hold_days,
                    "after": minimum_hold,
                }
            )
        hold_days = minimum_hold

    hold_tuning["profile_hold_floor"] = minimum_hold or None
    hold_tuning["final_hold_days"] = hold_days
    return hold_days


def build_strategy_candidates(
    market_data: MarketData,
    gemini_result: GeminiAnalysisResult | None = None,
    section_type: SectionType | None = None,
) -> tuple[list[StrategyCandidate], dict[str, object]]:
    direction_sign = _direction_sign(gemini_result)
    bullish_bias = max(0.0, direction_sign)
    bearish_bias = max(0.0, -direction_sign)
    relative_strength_points = _percentage_points(market_data.relative_strength_20d)
    sector_momentum_points = _percentage_points(market_data.sector_momentum)

    gap_strength = _scaled_abs(market_data.gap_pct, 6.0)
    drift_strength = _scaled_abs(market_data.post_earnings_drift_pct, 8.0)
    surprise_strength = _scaled_abs(market_data.surprise_pct, 12.0)
    squeeze_strength = _clamp((market_data.short_interest_pct_float / 20.0) + (market_data.float_rotation / 3.0))
    iv_strength = _clamp(market_data.iv_rank / 100.0)
    volume_strength = _clamp((market_data.volume_ratio - 1.0) / 2.5)
    reversal_strength = _clamp(max(0.0, -market_data.day1_return_pct) / 8.0)
    trend_strength = _clamp(max(0.0, relative_strength_points) / 15.0)
    sector_strength = _clamp(max(0.0, sector_momentum_points) / 10.0)
    benchmark_strength = _benchmark_support(market_data)
    technical_trend_strength = _technical_trend_support(market_data)
    fundamental_strength = _fundamental_support(market_data)
    exhaustion_strength = _exhaustion_score(market_data)
    bullish_options_flow = _options_flow_support(market_data, bullish=True)
    bearish_options_flow = _options_flow_support(market_data, bullish=False)
    near_earnings_risk = 1.0 if market_data.next_earnings_days is not None and market_data.next_earnings_days <= 3 else 0.0
    liquidity_penalty = 0.10 if (market_data.liquidity_score is not None and market_data.liquidity_score < 0.45) else 0.0
    spread_penalty = 0.08 if (market_data.current_iv is not None and market_data.current_iv > 1.2 and market_data.volume_ratio < 1.2) else 0.0

    transcript_signals = _transcript_signals(gemini_result)
    transcript_continuation_support = _transcript_continuation_score(gemini_result)
    transcript_reversal_support = _clamp(-transcript_continuation_support, 0.0, 1.0)
    implied_gap_overshoot = _implied_gap_overshoot(market_data)
    overshoot_penalty = _clamp(implied_gap_overshoot / 0.8, 0.0, 0.35)
    overshoot_reversion_bonus = _clamp(implied_gap_overshoot / 0.8, 0.0, 0.22)

    analysis_map = gemini_result.model_dump() if gemini_result is not None else None
    gap_event_quality = score_event_quality(market_data, analysis_map, strategy=StrategyName.GAP_AND_GO)
    pead_event_quality = score_event_quality(market_data, analysis_map, strategy=StrategyName.PEAD)
    news_event_quality = score_event_quality(market_data, analysis_map, strategy=StrategyName.NEWS_BREAKOUT)

    candidates = [
        StrategyCandidate(
            StrategyName.WHISPER_PLAY,
            0.28 * surprise_strength
            + 0.22 * gap_strength
            + 0.16 * volume_strength
            + 0.14 * drift_strength
            + 0.10 * bullish_bias
            + 0.08 * max(0.0, transcript_continuation_support)
            + 0.05 * technical_trend_strength
            + 0.04 * benchmark_strength
            + 0.04 * fundamental_strength
            + 0.03 * bullish_options_flow
            - overshoot_penalty,
            "earnings surprise + opening gap + volume expansion",
        ),
        StrategyCandidate(
            StrategyName.GAP_AND_GO,
            0.24 * gap_strength
            + 0.16 * volume_strength
            + 0.12 * trend_strength
            + 0.10 * bullish_bias
            + 0.24 * gap_event_quality.total
            + 0.08 * max(0.0, transcript_continuation_support)
            + 0.08 * technical_trend_strength
            + 0.05 * benchmark_strength
            + 0.04 * fundamental_strength
            + 0.03 * bullish_options_flow
            - liquidity_penalty
            - overshoot_penalty,
            "strong opening gap supported by event quality, tape strength, and follow-through",
        ),
        StrategyCandidate(
            StrategyName.GAP_FILL,
            0.30 * gap_strength
            + 0.26 * reversal_strength
            + 0.14 * iv_strength
            + 0.08 * bearish_bias
            + 0.10 * (1.0 - trend_strength)
            + 0.10 * transcript_reversal_support
            + 0.10 * exhaustion_strength
            + 0.06 * (1.0 - technical_trend_strength)
            + 0.04 * bearish_options_flow
            + overshoot_reversion_bonus,
            "exhaustive gap with fade/reversion characteristics",
        ),
        StrategyCandidate(
            StrategyName.SHORT_SQUEEZE,
            0.38 * squeeze_strength
            + 0.16 * volume_strength
            + 0.12 * gap_strength
            + 0.10 * trend_strength
            + 0.12 * bullish_bias
            + 0.06 * max(0.0, transcript_continuation_support)
            + 0.03 * benchmark_strength
            + 0.03 * bullish_options_flow,
            "crowded short setup with rotation and tape confirmation",
        ),
        StrategyCandidate(
            StrategyName.IV_CRUSH_DECAY,
            0.40 * iv_strength
            + 0.14 * surprise_strength
            + 0.10 * volume_strength
            + 0.08 * bearish_bias
            + 0.10 * near_earnings_risk
            + 0.08 * (1.0 - drift_strength)
            + 0.05 * exhaustion_strength
            + 0.05 * bearish_options_flow,
            "elevated implied volatility with limited drift persistence",
        ),
        StrategyCandidate(
            StrategyName.PEAD,
            0.24 * drift_strength
            + 0.16 * surprise_strength
            + 0.10 * trend_strength
            + 0.08 * volume_strength
            + 0.22 * pead_event_quality.total
            + 0.08 * bullish_bias
            + 0.10 * max(0.0, transcript_continuation_support)
            + 0.08 * technical_trend_strength
            + 0.05 * benchmark_strength
            + 0.04 * fundamental_strength
            + 0.03 * bullish_options_flow
            - overshoot_penalty * 0.65,
            "post-earnings drift continuation supported by strong event quality",
        ),
        StrategyCandidate(
            StrategyName.REVERSAL_CATALYST,
            0.30 * reversal_strength
            + 0.16 * iv_strength
            + 0.12 * volume_strength
            + 0.12 * gap_strength
            + 0.16 * bearish_bias
            + 0.10 * transcript_reversal_support
            + 0.10 * exhaustion_strength
            + 0.06 * (1.0 - technical_trend_strength)
            + 0.04 * bearish_options_flow
            + overshoot_reversion_bonus,
            "sharp initial rejection with mean-reversion opportunity",
        ),
        StrategyCandidate(
            StrategyName.NEWS_BREAKOUT,
            0.16 * trend_strength
            + 0.12 * volume_strength
            + 0.08 * gap_strength
            + 0.10 * sector_strength
            + 0.30 * news_event_quality.total
            + 0.10 * bullish_bias
            + 0.08 * max(0.0, transcript_continuation_support)
            + 0.06 * technical_trend_strength
            + 0.05 * benchmark_strength
            + 0.05 * fundamental_strength
            + 0.03 * bullish_options_flow
            - spread_penalty
            - overshoot_penalty * 0.50,
            "broad tape breakout reinforced by sector follow-through and headline quality",
        ),
        StrategyCandidate(
            StrategyName.MOMENTUM_CARRY,
            0.20 * drift_strength
            + 0.16 * trend_strength
            + 0.10 * volume_strength
            + 0.10 * sector_strength
            + 0.08 * bullish_bias
            + 0.10 * max(0.0, transcript_continuation_support)
            + 0.08 * pead_event_quality.total
            + 0.08 * technical_trend_strength
            + 0.06 * benchmark_strength
            + 0.04 * fundamental_strength
            + 0.03 * bullish_options_flow
            - overshoot_penalty * 0.35,
            "multi-day momentum carry with trend and transcript confirmation",
        ),
    ]

    metadata: dict[str, object] = {
        "event_quality": {
            "gap_and_go": gap_event_quality.to_dict(),
            "pead": pead_event_quality.to_dict(),
            "news_breakout": news_event_quality.to_dict(),
        },
        "section_type": section_type.value if isinstance(section_type, SectionType) else None,
        "transcript_context": {
            "continuation_support": round(transcript_continuation_support, 4),
            "reversal_support": round(transcript_reversal_support, 4),
            "implied_gap_overshoot": round(implied_gap_overshoot, 4),
            "has_transcript_signals": bool(transcript_signals),
        },
        "market_feature_context": {
            "benchmark_strength": round(benchmark_strength, 4),
            "technical_trend_strength": round(technical_trend_strength, 4),
            "fundamental_strength": round(fundamental_strength, 4),
            "exhaustion_strength": round(exhaustion_strength, 4),
            "bullish_options_flow": round(bullish_options_flow, 4),
            "bearish_options_flow": round(bearish_options_flow, 4),
        },
    }
    return candidates, metadata


def choose_strategy(
    market_data: MarketData,
    gemini_result: GeminiAnalysisResult | None = None,
    section_type: SectionType | None = None,
    universe_profile: str | None = None,
    risk_style: str | None = None,
) -> StrategyDecision:
    settings = get_settings()
    candidates, metadata = build_strategy_candidates(market_data, gemini_result=gemini_result, section_type=section_type)
    profile = _resolve_strategy_profile(market_data=market_data, universe_profile=universe_profile, risk_style=risk_style)
    allowed_strategies = set(get_allowed_strategies(profile))
    if allowed_strategies:
        candidates = [item for item in candidates if item.strategy in allowed_strategies]
    if not candidates:
        candidates = [StrategyCandidate(StrategyName.SENTIMENT_ONLY, 0.35, "no allowed tactical setup remained after profile filtering")]
    candidates = sorted(candidates, key=lambda item: item.score, reverse=True)
    best = candidates[0]
    risk_flags: list[str] = []
    regime = _classify_regime(market_data)
    estimated_execution_cost_pct = _estimated_execution_cost_pct(market_data, settings)
    metadata["execution_cost_model"] = {
        "estimated_all_in_cost_pct": round(estimated_execution_cost_pct, 4),
        "bid_ask_spread_bps": market_data.bid_ask_spread_bps,
        "latency_bps": float(settings.execution_latency_bps_default),
        "limit_pct": float(settings.conservative_execution_cost_limit_pct),
    }

    if market_data.vix >= settings.max_vix:
        risk_flags.append("high_vix")
    if (
        profile.risk_style_name == RiskStyleName.CONSERVATIVE
        and estimated_execution_cost_pct > float(settings.conservative_execution_cost_limit_pct)
    ):
        risk_flags.append("execution_cost_above_conservative_limit")
        best = StrategyCandidate(
            StrategyName.SENTIMENT_ONLY,
            min(best.score, 0.35),
            "estimated spread and latency cost is too high for conservative execution",
        )
    if market_data.volume_ratio < settings.min_volume_ratio:
        risk_flags.append("thin_confirmation")
    if market_data.beta_20d > 2.0:
        risk_flags.append("high_beta")
    if market_data.rsi_14 is not None and market_data.rsi_14 >= 76:
        risk_flags.append("overextended_rsi")
    if market_data.next_earnings_days is not None and market_data.next_earnings_days <= 3:
        risk_flags.append("near_earnings")
    if market_data.hours_since_news is not None and market_data.hours_since_news >= 72:
        risk_flags.append("stale_catalyst")
    if market_data.current_price and market_data.ma200 and float(market_data.current_price) < float(market_data.ma200):
        risk_flags.append("below_ma200")
    if str(market_data.ichimoku_weekly_cloud_bias or "").lower() == "bearish":
        risk_flags.append("weekly_cloud_bearish")
    if (
        market_data.stochastic_k is not None
        and float(market_data.stochastic_k) >= 85.0
        and market_data.bb_position is not None
        and float(market_data.bb_position) >= 0.92
    ):
        risk_flags.append("stacked_overbought")
    benchmark_weak = False
    benchmark_values = [value for value in [market_data.spy_relative_strength_20d, market_data.qqq_relative_strength_20d] if value is not None]
    if benchmark_values and max(float(value) for value in benchmark_values) <= -4.0:
        benchmark_weak = True
        risk_flags.append("benchmark_underperformance")
    weak_fundamentals = (
        market_data.revenue_growth_yoy is not None
        and market_data.earnings_growth_yoy is not None
        and float(market_data.revenue_growth_yoy) < 0.0
        and float(market_data.earnings_growth_yoy) < 0.0
        and (
            (market_data.operating_margin is not None and float(market_data.operating_margin) < 8.0)
            or (market_data.debt_to_equity is not None and float(market_data.debt_to_equity) > 180.0)
        )
    )
    if weak_fundamentals:
        risk_flags.append("weak_fundamentals")
    zero_dte_flow_opposition = False
    if market_data.zero_dte_available:
        gamma_pressure = float(market_data.zero_dte_gamma_pressure or 0.0)
        put_call_ratio = float(market_data.zero_dte_put_call_volume_ratio or 1.0)
        bullish_flow_conflict = gamma_pressure <= -0.15 or put_call_ratio >= 1.20
        bearish_flow_conflict = gamma_pressure >= 0.15 or put_call_ratio <= 0.85
        if (gemini_result is not None and gemini_result.direction == "BULLISH" and bullish_flow_conflict) or (
            gemini_result is not None and gemini_result.direction == "BEARISH" and bearish_flow_conflict
        ):
            zero_dte_flow_opposition = True
            risk_flags.append("zero_dte_flow_opposition")

    transcript_context = metadata.get("transcript_context") if isinstance(metadata.get("transcript_context"), dict) else {}
    implied_gap_overshoot = float(transcript_context.get("implied_gap_overshoot", 0.0) or 0.0)
    continuation_support = float(transcript_context.get("continuation_support", 0.0) or 0.0)
    if regime in set(profile.gate.blocked_regimes):
        risk_flags.append(f"{regime}_regime_blocked")
        best = StrategyCandidate(
            StrategyName.SENTIMENT_ONLY,
            min(best.score, 0.35),
            "active profile blocks tactical continuation entries in this market regime",
        )
    if implied_gap_overshoot >= 0.20:
        risk_flags.append("gap_overshot_implied_move")
    if implied_gap_overshoot >= 0.35 and continuation_support <= 0.10:
        risk_flags.append("overshoot_without_transcript_confirmation")

    event_quality = metadata["event_quality"]
    if best.strategy == StrategyName.GAP_AND_GO and event_quality["gap_and_go"]["total"] < 0.56:
        risk_flags.append("low_event_quality")
        best = _fallback_candidate(
            candidates=candidates,
            current=best,
            preferred=(StrategyName.PEAD, StrategyName.NEWS_BREAKOUT, StrategyName.MOMENTUM_CARRY),
            rationale="gap-and-go quality was too weak, so the engine fell back to a safer setup",
        )
    elif best.strategy == StrategyName.NEWS_BREAKOUT and event_quality["news_breakout"]["total"] < 0.60:
        risk_flags.append("low_event_quality")
        best = _fallback_candidate(
            candidates=candidates,
            current=best,
            preferred=(StrategyName.PEAD, StrategyName.GAP_AND_GO, StrategyName.MOMENTUM_CARRY),
            rationale="news-breakout quality was too weak, so the engine fell back to a safer setup",
        )
    elif best.strategy == StrategyName.PEAD and event_quality["pead"]["total"] < 0.58:
        risk_flags.append("low_event_quality")
        best = _fallback_candidate(
            candidates=candidates,
            current=best,
            preferred=(StrategyName.NEWS_BREAKOUT, StrategyName.GAP_AND_GO, StrategyName.MOMENTUM_CARRY),
            rationale="PEAD quality was too weak, so the engine fell back to a safer setup",
        )

    continuation_candidates = {
        StrategyName.GAP_AND_GO,
        StrategyName.WHISPER_PLAY,
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
        StrategyName.SHORT_SQUEEZE,
    }
    if best.strategy in continuation_candidates and (
        ("below_ma200" in risk_flags or "weekly_cloud_bearish" in risk_flags)
        and profile.risk_style_name == RiskStyleName.CONSERVATIVE
    ):
        replacement = _fallback_candidate(
            candidates=candidates,
            current=best,
            preferred=(StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST, StrategyName.SENTIMENT_ONLY),
            rationale="higher timeframe trend structure was weak, so the engine fell back to a safer setup",
        )
        best = replacement if replacement.strategy not in continuation_candidates else StrategyCandidate(
            StrategyName.SENTIMENT_ONLY,
            min(best.score, 0.35),
            "higher timeframe trend structure was weak, so the engine fell back to a short-horizon sentiment-only setup",
        )

    if best.strategy in continuation_candidates and (
        "benchmark_underperformance" in risk_flags or "zero_dte_flow_opposition" in risk_flags
    ):
        replacement = _fallback_candidate(
            candidates=candidates,
            current=best,
            preferred=(StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST, StrategyName.SENTIMENT_ONLY),
            rationale="cross-market or same-day options flow context conflicted with continuation, so the engine fell back to a safer setup",
        )
        best = replacement if replacement.strategy not in continuation_candidates else StrategyCandidate(
            StrategyName.SENTIMENT_ONLY,
            min(best.score, 0.35),
            "cross-market or same-day options flow context conflicted with continuation, so the engine fell back to sentiment-only",
        )

    if (
        profile.name == UniverseName.NASDAQ100
        and profile.risk_style_name == RiskStyleName.CONSERVATIVE
        and best.strategy in continuation_candidates
        and (
            not nasdaq100_conservative_sector_allowed(market_data.sector_code)
            or nasdaq100_conservative_high_vol_news_blocked(best.strategy.value, regime)
            or
            "overextended_rsi" in risk_flags
            or "stacked_overbought" in risk_flags
            or (
                best.strategy in {
                    StrategyName.PEAD,
                    StrategyName.MOMENTUM_CARRY,
                    StrategyName.GAP_AND_GO,
                    StrategyName.WHISPER_PLAY,
                }
                and nasdaq100_conservative_gap_extended(market_data.gap_pct)
            )
            or (
                best.strategy == StrategyName.NEWS_BREAKOUT
                and float(market_data.gap_pct or 0.0) > 0.0
                and nasdaq100_conservative_gap_extended(market_data.gap_pct)
            )
        )
    ):
        if not nasdaq100_conservative_sector_allowed(market_data.sector_code):
            risk_flags.append("nasdaq_conservative_non_core_sector")
        if nasdaq100_conservative_high_vol_news_blocked(best.strategy.value, regime):
            risk_flags.append("nasdaq_conservative_high_vol_news_breakout")
        if "overextended_rsi" in risk_flags or "stacked_overbought" in risk_flags:
            risk_flags.append("nasdaq_conservative_overextended")
        if (
            (
                best.strategy in {StrategyName.PEAD, StrategyName.MOMENTUM_CARRY, StrategyName.GAP_AND_GO, StrategyName.WHISPER_PLAY}
                or (best.strategy == StrategyName.NEWS_BREAKOUT and float(market_data.gap_pct or 0.0) > 0.0)
            )
            and nasdaq100_conservative_gap_extended(market_data.gap_pct)
        ):
            risk_flags.append("nasdaq_gap_extended")
        best = StrategyCandidate(
            StrategyName.SENTIMENT_ONLY,
            min(best.score, 0.35),
            "Nasdaq100 conservative continuation filter rejected an extended setup, so the engine fell back to sentiment-only",
        )

    if (
        profile.name == UniverseName.NASDAQ100
        and profile.risk_style_name == RiskStyleName.CONSERVATIVE
        and best.strategy == StrategyName.REVERSAL_CATALYST
    ):
        if nasdaq100_conservative_quality_reversal_allowed(
            sector_code=market_data.sector_code,
            market_cap_bucket=market_data.market_cap_bucket,
            regime=regime,
        ):
            risk_flags.append("nasdaq_conservative_quality_reversal_sleeve")
        else:
            risk_flags.append("nasdaq_conservative_quality_reversal_scope")
            best = StrategyCandidate(
                StrategyName.SENTIMENT_ONLY,
                min(best.score, 0.35),
                "Nasdaq100 conservative quality-reversal sleeve rejected this non-core reversal setup",
            )

    if best.strategy in {StrategyName.GAP_AND_GO, StrategyName.WHISPER_PLAY, StrategyName.PEAD, StrategyName.NEWS_BREAKOUT, StrategyName.MOMENTUM_CARRY}:
        if implied_gap_overshoot >= 0.55 and continuation_support <= 0.05:
            risk_flags.append("continuation_gate_failed")
            best = _fallback_candidate(
                candidates=candidates,
                current=best,
                preferred=(StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST),
                rationale="continuation quality was weak, so the engine fell back to a safer setup",
            )

    selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)
    if regime == "trend_up" and best.strategy in {
        StrategyName.PEAD,
        StrategyName.GAP_AND_GO,
        StrategyName.WHISPER_PLAY,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
    }:
        trend_up_quality_floor = 0.66 if profile.risk_style_name == RiskStyleName.CONSERVATIVE else 0.60
        trend_up_volume_floor = 2.0 if profile.risk_style_name == RiskStyleName.CONSERVATIVE else 1.8
        breakout_floor = 0.015
        if (
            float(selected_event_quality or 0.0) < trend_up_quality_floor
            or float(market_data.volume_ratio or 0.0) < trend_up_volume_floor
            or float(market_data.breakout_20d_pct or 0.0) < breakout_floor
            or continuation_support < 0.05
        ):
            risk_flags.append("trend_up_confirmation_gap")
            best = _fallback_candidate(
                candidates=candidates,
                current=best,
                preferred=(StrategyName.GAP_AND_GO, StrategyName.NEWS_BREAKOUT, StrategyName.MOMENTUM_CARRY, StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST),
                rationale="trend-up continuation lacked confirmation, so the engine fell back to a safer setup",
            )
            selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)

    if profile.name == UniverseName.SP500 and best.strategy == StrategyName.PEAD:
        sp500_pead_quality_floor = 0.72 if profile.risk_style_name == RiskStyleName.CONSERVATIVE else 0.66
        sp500_volume_floor = 2.2 if profile.risk_style_name == RiskStyleName.CONSERVATIVE else 1.9
        sp500_surprise_floor = 10.0 if profile.risk_style_name == RiskStyleName.CONSERVATIVE else 8.0
        sp500_rs_floor = 8.0 if profile.risk_style_name == RiskStyleName.CONSERVATIVE else 5.0
        sp500_hours_max = 18.0 if profile.risk_style_name == RiskStyleName.CONSERVATIVE else 24.0
        if (
            float(selected_event_quality or 0.0) < sp500_pead_quality_floor
            or float(market_data.volume_ratio or 0.0) < sp500_volume_floor
            or float(market_data.surprise_pct or 0.0) < sp500_surprise_floor
            or _percentage_points(market_data.relative_strength_20d) < sp500_rs_floor
            or float(market_data.hours_since_news or 999.0) > sp500_hours_max
        ):
            risk_flags.append("sp500_pead_quality_gate_failed")
            best = _fallback_candidate(
                candidates=candidates,
                current=best,
                preferred=(StrategyName.GAP_AND_GO, StrategyName.NEWS_BREAKOUT, StrategyName.MOMENTUM_CARRY, StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST),
                rationale="SP500 PEAD quality gate rejected the setup, so the engine fell back to a safer setup",
            )
            selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)

    if (
        profile.name == UniverseName.SP500
        and profile.risk_style_name == RiskStyleName.CONSERVATIVE
        and best.strategy == StrategyName.GAP_AND_GO
        and sp500_conservative_gap_sector_blocked(market_data.sector_code)
    ):
        risk_flags.append("sp500_gap_sector_blocked")
        best = StrategyCandidate(
            StrategyName.SENTIMENT_ONLY,
            min(best.score, 0.35),
            "SP500 conservative sector filter rejected the continuation setup, so the engine fell back to sentiment-only",
        )
        selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)

    if (
        profile.name == UniverseName.NASDAQ100
        and profile.risk_style_name == RiskStyleName.AGGRESSIVE
        and best.strategy != StrategyName.SENTIMENT_ONLY
    ):
        if not nasdaq100_aggressive_strategy_allowed(best.strategy.value):
            risk_flags.append("nasdaq_aggressive_strategy_blocked")
            reversal_candidate = next(
                (item for item in candidates if item.strategy == StrategyName.REVERSAL_CATALYST and item.strategy != best.strategy),
                None,
            )
            if (
                reversal_candidate is not None
                and not nasdaq100_aggressive_sector_blocked(market_data.sector_code)
                and nasdaq100_aggressive_rotation_allowed(market_data.sector_code)
            ):
                best = StrategyCandidate(
                    reversal_candidate.strategy,
                    reversal_candidate.score,
                    "Nasdaq100 aggressive research track rotated the setup into the allowed reversal sleeve",
                )
            else:
                best = StrategyCandidate(
                    StrategyName.SENTIMENT_ONLY,
                    min(best.score, 0.35),
                    "Nasdaq100 aggressive research track now only allows selected reversal setups",
                )
            selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)
        elif nasdaq100_aggressive_sector_blocked(market_data.sector_code):
            risk_flags.append("nasdaq_aggressive_sector_blocked")
            best = StrategyCandidate(
                StrategyName.SENTIMENT_ONLY,
                min(best.score, 0.35),
                "Nasdaq100 aggressive research track rejected the setup because the reversal sector cohort stayed too weak",
            )
            selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)

    if (
        profile.name == UniverseName.SP500
        and profile.risk_style_name == RiskStyleName.AGGRESSIVE
        and best.strategy != StrategyName.SENTIMENT_ONLY
    ):
        if not sp500_aggressive_strategy_allowed(best.strategy.value):
            risk_flags.append("sp500_aggressive_strategy_blocked")
            best = StrategyCandidate(
                StrategyName.SENTIMENT_ONLY,
                min(best.score, 0.35),
                "SP500 aggressive research track now only allows selected PEAD setups",
            )
            selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)
        elif sp500_aggressive_sector_blocked(market_data.sector_code):
            risk_flags.append("sp500_aggressive_sector_blocked")
            best = StrategyCandidate(
                StrategyName.SENTIMENT_ONLY,
                min(best.score, 0.35),
                "SP500 aggressive research track rejected the setup because the PEAD sector cohort stayed too weak",
            )
            selected_event_quality = _event_quality_for_strategy(best.strategy, metadata)

    if best.score < 0.36:
        risk_flags.append("weak_setup")
        best = StrategyCandidate(StrategyName.SENTIMENT_ONLY, best.score, "no strong tactical edge; default to short-horizon sentiment signal")

    base_hold_days = _base_horizon_days(best.strategy)
    hold_days, hold_tuning = _tune_hold_days(
        base_hold_days=base_hold_days,
        strategy=best.strategy,
        score=best.score,
        market_data=market_data,
        gemini_result=gemini_result,
        risk_flags=risk_flags,
        metadata=metadata,
    )
    hold_days = _apply_profile_hold_floor(
        hold_days=hold_days,
        strategy=best.strategy,
        profile=profile,
        regime=regime,
        event_quality=selected_event_quality,
        market_data=market_data,
        risk_flags=risk_flags,
        hold_tuning=hold_tuning,
    )

    metadata.update(
        {
            "ranked_candidates": [
                {"strategy": item.strategy.value, "score": round(item.score, 4)} for item in candidates[:5]
            ],
            "selected_after_filters": best.strategy.value,
            "hold_tuning": hold_tuning,
            "strategy_profile": {
                "name": profile.name.value,
                "risk_style": profile.risk_style_name.value,
                "requested_universe_profile": universe_profile,
                "requested_risk_style": risk_style,
                "allowed_strategies": [item.value for item in get_allowed_strategies(profile)],
                "regime": regime,
            },
        }
    )

    return StrategyDecision(
        strategy=best.strategy,
        score=round(best.score, 4),
        hold_days=hold_days,
        rationale=best.rationale,
        risk_flags=risk_flags,
        metadata=metadata,
    )
