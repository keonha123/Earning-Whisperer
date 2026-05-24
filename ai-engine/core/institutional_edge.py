"""Institution-grade signal evidence, execution, and red-team scoring."""

from __future__ import annotations

from typing import Any

try:
    from models.request_models import MarketData, SourceType
    from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
except ImportError:  # pragma: no cover
    from ..models.request_models import MarketData, SourceType
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


_ACTIONABLE_STRATEGIES = {
    StrategyName.PEAD,
    StrategyName.NEWS_BREAKOUT,
    StrategyName.MOMENTUM_CARRY,
    StrategyName.GAP_AND_GO,
    StrategyName.GAP_FILL,
    StrategyName.REVERSAL_CATALYST,
    StrategyName.SHORT_SQUEEZE,
    StrategyName.WHISPER_PLAY,
    StrategyName.IV_CRUSH_DECAY,
}

_SEVERE_RISK_FLAGS = {
    "low_event_quality",
    "weak_setup",
    "continuation_gate_failed",
    "risk_off_regime_blocked",
    "high_vol_regime_blocked",
    "overshoot_without_transcript_confirmation",
    "gap_overshot_implied_move",
    "zero_dte_flow_opposition",
    "weak_fundamentals",
}

_MILD_RISK_FLAGS = {
    "thin_confirmation",
    "high_vix",
    "high_beta",
    "stale_catalyst",
    "overextended_rsi",
    "below_ma200",
    "weekly_cloud_bearish",
    "benchmark_underperformance",
}


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _grade(score: float) -> str:
    if score >= 0.82:
        return "A"
    if score >= 0.68:
        return "B"
    if score >= 0.52:
        return "C"
    if score >= 0.36:
        return "D"
    return "E"


def _evidence_score(
    *,
    analysis: GeminiAnalysisResult,
    signal_explanation: dict[str, Any],
    source_type: SourceType,
) -> tuple[float, list[str]]:
    metadata = analysis.metadata if isinstance(analysis.metadata, dict) else {}
    feature_bundle = metadata.get("feature_bundle") if isinstance(metadata.get("feature_bundle"), dict) else {}
    source_summary = metadata.get("source_health_summary") if isinstance(metadata.get("source_health_summary"), dict) else {}

    coverage_pct = _safe_float(feature_bundle.get("coverage_pct"), 0.0) / 100.0
    source_coverage_pct = _safe_float(source_summary.get("coverage_pct"), 0.0) / 100.0
    contribution_count = len(signal_explanation.get("feature_contributions") or [])
    driver_count = len(signal_explanation.get("top_drivers") or [])
    disagreement = _safe_float(analysis.disagreement_score, 0.0)

    score = _clamp(
        0.34 * _clamp(analysis.confidence)
        + 0.16 * min(1.0, contribution_count / 3.0)
        + 0.14 * min(1.0, driver_count / 3.0)
        + 0.13 * max(coverage_pct, source_coverage_pct)
        + 0.10 * (1.0 if source_type in {SourceType.EARNINGS_CALL, SourceType.FILING, SourceType.NEWS} else 0.55)
        + 0.08 * (1.0 if metadata.get("llm_error") is None else 0.0)
        + 0.05 * (1.0 - _clamp(disagreement))
    )

    gaps: list[str] = []
    if contribution_count == 0:
        gaps.append("missing_feature_contributions")
    if driver_count == 0:
        gaps.append("missing_top_drivers")
    if coverage_pct < 0.25 and source_coverage_pct < 0.25:
        gaps.append("low_source_coverage")
    if metadata.get("llm_error") is not None:
        gaps.append("llm_fallback")
    if disagreement >= 0.45:
        gaps.append("high_model_disagreement")
    return score, gaps


def _execution_score(*, market_data: MarketData, trade_plan: dict[str, Any] | None) -> tuple[float, list[str]]:
    trade_plan = trade_plan if isinstance(trade_plan, dict) else {}
    volume_ratio = _safe_float(market_data.volume_ratio, 1.0)
    liquidity_score = _safe_float(market_data.liquidity_score, 0.55)
    spread_bps = _safe_float(market_data.bid_ask_spread_bps, 35.0)
    atr_pct = _safe_float(market_data.atr_pct_14, 2.5)
    available = bool(trade_plan.get("available", False))
    has_stop = trade_plan.get("stop_loss") is not None
    has_entry = bool(trade_plan.get("entry_zone"))

    spread_component = 1.0 - _clamp((spread_bps - 8.0) / 92.0)
    atr_component = 1.0 - _clamp((atr_pct - 2.0) / 10.0)
    score = _clamp(
        0.24 * _clamp(volume_ratio / 2.2)
        + 0.20 * _clamp(liquidity_score)
        + 0.18 * spread_component
        + 0.14 * atr_component
        + 0.12 * (1.0 if available else 0.0)
        + 0.07 * (1.0 if has_stop else 0.0)
        + 0.05 * (1.0 if has_entry else 0.0)
    )

    blockers: list[str] = []
    if not available:
        blockers.append("no_trade_plan")
    if spread_bps > 75:
        blockers.append("wide_spread")
    if liquidity_score < 0.35:
        blockers.append("low_liquidity")
    if volume_ratio < 0.8:
        blockers.append("weak_volume_confirmation")
    if not has_stop:
        blockers.append("missing_stop_loss")
    return score, blockers


def _risk_score(*, risk_flags: list[str], trade_plan: dict[str, Any] | None) -> tuple[float, list[str]]:
    trade_plan = trade_plan if isinstance(trade_plan, dict) else {}
    severe_count = sum(1 for flag in risk_flags if flag in _SEVERE_RISK_FLAGS)
    mild_count = sum(1 for flag in risk_flags if flag in _MILD_RISK_FLAGS)
    penalty = min(1.0, 0.22 * severe_count + 0.08 * mild_count + 0.03 * max(0, len(risk_flags) - severe_count - mild_count))
    risk_control_bonus = 0.0
    if trade_plan.get("stop_loss") is not None:
        risk_control_bonus += 0.18
    if trade_plan.get("time_stop_days") is not None:
        risk_control_bonus += 0.12
    if trade_plan.get("entry_zone"):
        risk_control_bonus += 0.10
    score = _clamp(1.0 - penalty + risk_control_bonus)

    kill_conditions: list[str] = []
    if severe_count:
        kill_conditions.append("severe_risk_flag_present")
    if "risk_off_regime_blocked" in risk_flags:
        kill_conditions.append("risk_off_regime")
    if "gap_overshot_implied_move" in risk_flags:
        kill_conditions.append("gap_beyond_implied_move")
    if "zero_dte_flow_opposition" in risk_flags:
        kill_conditions.append("same_day_options_flow_opposes_signal")
    if trade_plan.get("stop_loss") is not None:
        kill_conditions.append("invalidate_if_stop_loss_breached")
    if trade_plan.get("time_stop_days") is not None:
        kill_conditions.append("time_stop_without_follow_through")
    return score, kill_conditions


def _uniqueness_score(
    *,
    market_data: MarketData,
    strategy_decision: StrategyDecision,
    analysis: GeminiAnalysisResult,
    source_type: SourceType,
) -> tuple[float, list[str]]:
    signals = [
        abs(_safe_float(market_data.surprise_pct)) >= 3.0,
        abs(_safe_float(market_data.gap_pct)) >= 2.0,
        _safe_float(market_data.volume_ratio, 1.0) >= 1.6,
        abs(_safe_float(market_data.relative_strength_20d)) >= 3.0,
        strategy_decision.strategy in _ACTIONABLE_STRATEGIES,
        source_type in {SourceType.EARNINGS_CALL, SourceType.FILING, SourceType.NEWS},
        str(analysis.direction).upper() in {"BULLISH", "BEARISH"},
    ]
    score = _clamp(sum(1 for item in signals if item) / len(signals))
    chips: list[str] = []
    if abs(_safe_float(market_data.surprise_pct)) >= 3.0:
        chips.append("earnings_surprise")
    if abs(_safe_float(market_data.gap_pct)) >= 2.0:
        chips.append("event_gap")
    if _safe_float(market_data.volume_ratio, 1.0) >= 1.6:
        chips.append("volume_confirmation")
    if abs(_safe_float(market_data.relative_strength_20d)) >= 3.0:
        chips.append("relative_strength_dislocation")
    if source_type == SourceType.EARNINGS_CALL:
        chips.append("earnings_call_context")
    return score, chips


def _capacity_snapshot(market_data: MarketData, execution_score: float) -> dict[str, Any]:
    price = _safe_float(market_data.current_price)
    avg_volume = _safe_float(market_data.avg_volume_20d)
    spread_bps = _safe_float(market_data.bid_ask_spread_bps, 35.0)
    participation = 0.004 if execution_score < 0.5 else 0.008 if execution_score < 0.72 else 0.015
    notional = None
    if price > 0 and avg_volume > 0:
        notional = round(price * avg_volume * participation, 2)
    return {
        "estimated_capacity_usd": notional,
        "max_participation_rate": round(participation, 4),
        "spread_bps": spread_bps,
        "slippage_budget_bps": round(max(12.0, min(90.0, spread_bps * 1.7 + 8.0)), 2),
        "capacity_method": "avg_volume_20d_participation" if notional is not None else "insufficient_volume_history",
    }


def _red_team(
    *,
    analysis: GeminiAnalysisResult,
    strategy_decision: StrategyDecision,
    signal_explanation: dict[str, Any],
    kill_conditions: list[str],
) -> dict[str, Any]:
    direction = str(analysis.direction).upper()
    drivers = signal_explanation.get("top_drivers") or signal_explanation.get("key_factors") or []
    risks = signal_explanation.get("top_risks") or signal_explanation.get("counterfactors") or []
    if direction in {"BULLISH", "LONG"}:
        opposing = "bear_case"
        opposite_thesis = "The setup fails if the event is already priced, volume fades, or the next session loses the entry zone."
    elif direction in {"BEARISH", "SHORT"}:
        opposing = "bull_case"
        opposite_thesis = "The short thesis fails if buyers reclaim the gap zone, guidance concerns are dismissed, or borrow/covering pressure dominates."
    else:
        opposing = "directional_case"
        opposite_thesis = "A neutral signal becomes tradable only if price, volume, and evidence converge on one direction."

    return {
        "primary_thesis": analysis.rationale,
        "opposing_thesis_type": opposing,
        "opposing_thesis": opposite_thesis,
        "what_would_change_mind": list(dict.fromkeys((risks or []) + kill_conditions))[:6],
        "must_confirm": list(dict.fromkeys(drivers or []))[:5],
        "strategy_under_review": strategy_decision.strategy.value,
    }


def _approval_state(score: float, evidence: float, execution: float, risk: float, analysis: GeminiAnalysisResult) -> str:
    tradable = str(analysis.direction).upper() in {"BULLISH", "BEARISH"} and _clamp(analysis.confidence) >= 0.45
    if tradable and score >= 0.76 and evidence >= 0.58 and execution >= 0.58 and risk >= 0.62:
        return "institutional_actionable"
    if tradable and score >= 0.60 and evidence >= 0.45:
        return "institutional_watch"
    if score >= 0.48:
        return "research_only"
    return "retail_summary_only"


def build_institutional_edge(
    *,
    market_data: MarketData,
    analysis: GeminiAnalysisResult,
    strategy_decision: StrategyDecision,
    source_type: SourceType,
    signal_explanation: dict[str, Any],
    trade_plan: dict[str, Any] | None,
    product_surface: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic institutional readiness package for a signal."""

    product_surface = product_surface if isinstance(product_surface, dict) else {}
    evidence_score, evidence_gaps = _evidence_score(
        analysis=analysis,
        signal_explanation=signal_explanation,
        source_type=source_type,
    )
    execution_score, execution_blockers = _execution_score(market_data=market_data, trade_plan=trade_plan)
    risk_score, kill_conditions = _risk_score(risk_flags=analysis.risk_flags or [], trade_plan=trade_plan)
    uniqueness_score, edge_chips = _uniqueness_score(
        market_data=market_data,
        strategy_decision=strategy_decision,
        analysis=analysis,
        source_type=source_type,
    )
    actionability = _safe_float(product_surface.get("actionability_score"), _clamp(strategy_decision.score))

    total = _clamp(
        0.24 * evidence_score
        + 0.22 * execution_score
        + 0.20 * risk_score
        + 0.16 * uniqueness_score
        + 0.10 * _clamp(analysis.confidence)
        + 0.08 * actionability
    )
    approval_state = _approval_state(total, evidence_score, execution_score, risk_score, analysis)

    priority_blockers: list[str] = []
    if strategy_decision.strategy not in _ACTIONABLE_STRATEGIES:
        priority_blockers.append("non_actionable_strategy")
    if str(analysis.direction).upper() not in {"BULLISH", "BEARISH"}:
        priority_blockers.append("no_directional_edge")
    blockers = list(dict.fromkeys(priority_blockers + evidence_gaps + execution_blockers))

    return {
        "schema_version": "2026-04-26.institutional-edge.v1",
        "institutional_grade_score": round(total * 100.0, 2),
        "grade": _grade(total),
        "approval_state": approval_state,
        "subscores": {
            "evidence_quality": round(evidence_score, 4),
            "execution_feasibility": round(execution_score, 4),
            "risk_control": round(risk_score, 4),
            "edge_distinctiveness": round(uniqueness_score, 4),
            "actionability": round(actionability, 4),
        },
        "capacity": _capacity_snapshot(market_data, execution_score),
        "blockers": list(dict.fromkeys(blockers))[:8],
        "kill_conditions": list(dict.fromkeys(kill_conditions))[:8],
        "edge_chips": list(dict.fromkeys(edge_chips))[:8],
        "red_team": _red_team(
            analysis=analysis,
            strategy_decision=strategy_decision,
            signal_explanation=signal_explanation,
            kill_conditions=kill_conditions,
        ),
        "moat_vs_retail_ai": [
            "auditable_evidence_score",
            "capacity_and_slippage_guard",
            "red_team_opposing_thesis",
            "runtime_control_and_replay_ready",
            "strategy_specific_gate_context",
        ],
        "frontend": {
            "badge": approval_state,
            "grade": _grade(total),
            "score": round(total * 100.0, 2),
            "summary": (
                "Institutional-ready signal package"
                if approval_state == "institutional_actionable"
                else "Requires review before institutional use"
            ),
            "driver_chips": list(dict.fromkeys(edge_chips))[:5],
            "risk_chips": list(dict.fromkeys(blockers + kill_conditions))[:5],
        },
    }


__all__ = ["build_institutional_edge"]
