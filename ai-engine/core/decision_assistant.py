"""Deterministic buy/sell judgment assistant for product-grade signal payloads."""

from __future__ import annotations

from typing import Any

try:
    from config import get_settings
    from models.request_models import MarketData, SourceType
    from models.signal_models import GeminiAnalysisResult, StrategyDecision
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from ..models.request_models import MarketData, SourceType
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision


_SCHEMA_VERSION = "2026-05-03.decision-assistant.v1"
_VALIDATED_NASDAQ100_CONSERVATIVE = {
    "available": True,
    "label": "검증 우수",
    "sample_count": 43,
    "win_rate_pct": 62.7907,
    "wilson_win_rate_lower_pct": 47.8595,
    "bayesian_win_rate_mean_pct": 62.2222,
    "avg_trade_return_pct": 0.6808,
    "total_return_pct": 31.277,
    "sharpe_ratio": 2.2955,
    "max_drawdown_pct": -11.4037,
    "simulation_mode": "price_proxy",
    "source_artifact": "data/backtests/nasdaq100_conservative_v957_quant_risk_20170120_20260426_proxy.json",
}
_VALIDATED_NASDAQ100_STRATEGIES = {
    "PEAD",
    "NEWS_BREAKOUT",
    "MOMENTUM_CARRY",
    "REVERSAL_CATALYST",
}
_HARD_RISK_FLAGS = {
    "continuation_gate_failed",
    "execution_cost_above_conservative_limit",
    "gap_overshot_implied_move",
    "low_event_quality",
    "management_contradiction_risk",
    "overshoot_without_transcript_confirmation",
    "risk_off_regime_blocked",
    "thin_confirmation",
    "weekly_cloud_bearish",
}
_SOFT_RISK_FLAGS = {
    "below_ma200",
    "negative_sentiment_velocity",
    "overextended_rsi",
    "qa_evasive_answer",
    "stochastic_overbought",
    "weak_fundamentals",
    "zero_dte_flow_opposition",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_round(value: Any, digits: int = 4) -> float:
    return round(_safe_float(value), digits)


def _strategy_value(strategy_decision: StrategyDecision | Any) -> str:
    strategy = getattr(strategy_decision, "strategy", None)
    return str(getattr(strategy, "value", strategy) or "UNKNOWN").upper()


def _risk_flags(analysis: GeminiAnalysisResult, strategy_decision: StrategyDecision | Any) -> list[str]:
    flags: list[str] = []
    for value in list(getattr(analysis, "risk_flags", []) or []) + list(getattr(strategy_decision, "risk_flags", []) or []):
        flag = str(value)
        if flag and flag not in flags:
            flags.append(flag)
    return flags


def _settings_cost_defaults() -> tuple[float, float, float, float]:
    try:
        settings = get_settings()
        return (
            _safe_float(settings.backtest_round_trip_cost_pct, 0.30),
            _safe_float(settings.slippage_bps_default, 8.0),
            _safe_float(settings.execution_latency_bps_default, 5.0),
            _safe_float(settings.conservative_execution_cost_limit_pct, 0.55),
        )
    except Exception:
        return 0.30, 8.0, 5.0, 0.55


def _execution_badge(market_data: MarketData, risk_flags: list[str]) -> dict[str, Any]:
    round_trip_pct, default_spread_bps, latency_bps, limit_pct = _settings_cost_defaults()
    spread_bps = _safe_float(getattr(market_data, "bid_ask_spread_bps", None), default_spread_bps)
    all_in_cost_pct = round_trip_pct + spread_bps / 100.0 + latency_bps / 100.0
    if all_in_cost_pct > limit_pct or "execution_cost_above_conservative_limit" in risk_flags:
        label = "진입 금지"
        reason = f"예상 왕복 실행비용 {all_in_cost_pct:.2f}%가 보수형 한도 {limit_pct:.2f}%를 초과합니다."
        severity = "block"
    elif all_in_cost_pct >= limit_pct * 0.82:
        label = "비용 주의"
        reason = f"예상 왕복 실행비용 {all_in_cost_pct:.2f}%가 한도에 근접해 지정가와 분할 진입이 필요합니다."
        severity = "warning"
    else:
        label = "실행 가능"
        reason = f"예상 왕복 실행비용 {all_in_cost_pct:.2f}%가 보수형 한도 {limit_pct:.2f}% 이내입니다."
        severity = "pass"
    return {
        "label": label,
        "severity": severity,
        "estimated_all_in_cost_pct": round(all_in_cost_pct, 4),
        "round_trip_cost_pct": round(round_trip_pct, 4),
        "spread_bps_used": round(spread_bps, 4),
        "latency_bps_used": round(latency_bps, 4),
        "limit_pct": round(limit_pct, 4),
        "reason_ko": reason,
    }


def _replay_confidence_badge(strategy: str, metadata: dict[str, Any]) -> dict[str, Any]:
    replay = metadata.get("replay_confidence_badge") if isinstance(metadata.get("replay_confidence_badge"), dict) else None
    if replay:
        payload = dict(replay)
        payload.setdefault("available", True)
        payload.setdefault("label", "검증 보통")
        return payload
    universe_profile = str(metadata.get("universe_profile") or metadata.get("profile") or "").upper()
    risk_style = str(metadata.get("risk_style") or metadata.get("strategy_risk_style") or "CONSERVATIVE").upper()
    if strategy in _VALIDATED_NASDAQ100_STRATEGIES and (not universe_profile or "NASDAQ" in universe_profile) and risk_style != "AGGRESSIVE":
        return dict(_VALIDATED_NASDAQ100_CONSERVATIVE)
    return {
        "available": False,
        "label": "검증 부족",
        "sample_count": 0,
        "win_rate_pct": None,
        "wilson_win_rate_lower_pct": None,
        "max_drawdown_pct": None,
        "simulation_mode": "unknown",
        "source_artifact": None,
        "reason_ko": "현재 전략/유니버스 조합의 고정 replay badge가 없습니다. 실제 replay 또는 proxy artifact 생성 후 표시해야 합니다.",
    }


def _technical_risk_flags(market_data: MarketData) -> list[str]:
    flags: list[str] = []
    current_price = _safe_float(getattr(market_data, "current_price", None), 0.0)
    ma200 = _safe_float(getattr(market_data, "ma200", None), 0.0)
    if current_price > 0 and ma200 > 0 and current_price < ma200:
        flags.append("below_ma200")
    if str(getattr(market_data, "ichimoku_weekly_cloud_bias", "") or "").lower() in {"bearish", "down", "negative"}:
        flags.append("weekly_cloud_bearish")
    rsi = getattr(market_data, "rsi_14", None)
    if rsi is not None and _safe_float(rsi) >= 76.0:
        flags.append("overextended_rsi")
    stochastic_k = getattr(market_data, "stochastic_k", None)
    stochastic_d = getattr(market_data, "stochastic_d", None)
    if stochastic_k is not None and stochastic_d is not None and _safe_float(stochastic_k) > 88 and _safe_float(stochastic_k) < _safe_float(stochastic_d):
        flags.append("stochastic_overbought")
    zero_dte_pcr = getattr(market_data, "zero_dte_put_call_volume_ratio", None)
    if zero_dte_pcr is not None and _safe_float(zero_dte_pcr) >= 1.45:
        flags.append("zero_dte_flow_opposition")
    revenue_growth = getattr(market_data, "revenue_growth_yoy", None)
    earnings_growth = getattr(market_data, "earnings_growth_yoy", None)
    if revenue_growth is not None and earnings_growth is not None and _safe_float(revenue_growth) < 0 and _safe_float(earnings_growth) < 0:
        flags.append("weak_fundamentals")
    return flags


def _no_trade_explainer(
    *,
    direction: str,
    risk_flags: list[str],
    execution_badge: dict[str, Any],
    replay_badge: dict[str, Any],
    signal_explanation: dict[str, Any],
) -> dict[str, Any]:
    blocked_reasons: list[str] = []
    wait_for: list[str] = []
    if execution_badge.get("severity") == "block":
        blocked_reasons.append(execution_badge.get("reason_ko") or "실행비용이 한도를 초과했습니다.")
        wait_for.append("스프레드와 체결비용이 보수형 한도 이내로 내려오는지 확인")
    hard_flags = [flag for flag in risk_flags if flag in _HARD_RISK_FLAGS]
    if hard_flags:
        blocked_reasons.append(f"Hard risk blocker 감지: {', '.join(hard_flags[:3])}")
        wait_for.append("hard blocker 해소 또는 다음 이벤트 업데이트 확인")
    if direction not in {"BULLISH", "LONG", "BEARISH", "SHORT"}:
        blocked_reasons.append("방향성이 명확하지 않아 신규 진입 판단을 보류합니다.")
        wait_for.append("가격/거래량/뉴스 반응이 같은 방향으로 정렬되는지 확인")
    if not replay_badge.get("available"):
        wait_for.append("동일 전략/유니버스 replay 검증 샘플 확보")
    gate_failures = signal_explanation.get("gate_failures") or []
    if isinstance(gate_failures, list) and gate_failures:
        blocked_reasons.append(f"게이트 실패: {', '.join(str(item) for item in gate_failures[:3])}")
    blocked = bool(blocked_reasons)
    return {
        "blocked": blocked,
        "deny_summary_ko": blocked_reasons[0] if blocked else "현재는 신규 진입 차단 사유가 우세하지 않습니다.",
        "blocked_reasons": blocked_reasons,
        "what_to_wait_for": wait_for[:4] or ["진입 후 비용, 가격 반응, 리스크 플래그를 계속 추적"],
    }


def _portfolio_impact_map(market_data: MarketData, risk_flags: list[str], direction: str) -> dict[str, Any]:
    beta_spy = getattr(market_data, "beta_spy_60d", None)
    beta_qqq = getattr(market_data, "beta_qqq_60d", None)
    exposure_notes = []
    if getattr(market_data, "sector_code", None):
        exposure_notes.append(f"섹터 노출: {getattr(market_data, 'sector_code')}")
    if getattr(market_data, "market_cap_bucket", None):
        exposure_notes.append(f"시총 버킷: {getattr(market_data, 'market_cap_bucket')}")
    if beta_qqq is not None and _safe_float(beta_qqq) >= 1.35:
        exposure_notes.append("QQQ 민감도가 높아 나스닥 변동성 확대 시 포지션 축소 우선")
    if beta_spy is not None and _safe_float(beta_spy) >= 1.30:
        exposure_notes.append("SPY 베타가 높아 시장 급락일에는 신규 매수보다 리스크 관리 우선")
    impact = "increase_growth_beta" if direction in {"BULLISH", "LONG"} else "reduce_or_hedge_beta"
    if any(flag in risk_flags for flag in _HARD_RISK_FLAGS):
        impact = "risk_reduction_first"
    return {
        "impact_code": impact,
        "sector_code": getattr(market_data, "sector_code", None),
        "market_cap_bucket": getattr(market_data, "market_cap_bucket", None),
        "beta_spy_60d": _safe_round(beta_spy, 4) if beta_spy is not None else None,
        "beta_qqq_60d": _safe_round(beta_qqq, 4) if beta_qqq is not None else None,
        "relative_strength": {
            "stock_20d": _safe_round(getattr(market_data, "relative_strength_20d", None), 4),
            "spy_20d": _safe_round(getattr(market_data, "spy_relative_strength_20d", None), 4),
            "qqq_20d": _safe_round(getattr(market_data, "qqq_relative_strength_20d", None), 4),
        },
        "notes_ko": exposure_notes[:5] or ["포트폴리오 집중도 입력이 없으므로 단일 종목 기준으로 판단합니다."],
    }


def _sell_first_action(
    *,
    direction: str,
    confidence: float,
    magnitude: float,
    actionability_score: float,
    risk_flags: list[str],
    execution_badge: dict[str, Any],
    no_trade: dict[str, Any],
    replay_badge: dict[str, Any],
) -> dict[str, Any]:
    hard_count = sum(1 for flag in risk_flags if flag in _HARD_RISK_FLAGS)
    soft_count = sum(1 for flag in risk_flags if flag in _SOFT_RISK_FLAGS)
    recommended_change_pct = 0.0
    action = "HOLD"
    if no_trade.get("blocked"):
        action = "AVOID"
    elif direction in {"BEARISH", "SHORT"} and confidence >= 0.70:
        action = "EXIT" if hard_count >= 1 and magnitude >= 0.65 else "REDUCE"
        recommended_change_pct = -100.0 if action == "EXIT" else -35.0
    elif hard_count >= 2:
        action = "REDUCE"
        recommended_change_pct = -50.0
    elif hard_count == 1 or soft_count >= 3:
        action = "REDUCE"
        recommended_change_pct = -35.0
    elif direction in {"BULLISH", "LONG"} and confidence >= 0.72 and actionability_score >= 0.62 and execution_badge.get("severity") == "pass":
        action = "ADD"
        recommended_change_pct = 20.0 if replay_badge.get("available") else 10.0
    reason_bullets = []
    if replay_badge.get("available"):
        reason_bullets.append(f"검증 배지: 승률 {replay_badge.get('win_rate_pct')}%, MDD {replay_badge.get('max_drawdown_pct')}%")
    reason_bullets.append(execution_badge.get("reason_ko") or "실행비용 확인 필요")
    if risk_flags:
        reason_bullets.append(f"주요 리스크: {', '.join(risk_flags[:4])}")
    if action == "ADD":
        intent = "보유 중이면 제한적으로 증액, 신규 진입은 분할 매수 우선"
    elif action == "REDUCE":
        intent = "손익 실현 또는 리스크 축소를 우선"
    elif action == "EXIT":
        intent = "보유 포지션 청산 우선"
    elif action == "AVOID":
        intent = "신규 진입 금지, 기존 보유자는 리스크만 점검"
    else:
        intent = "현재 비중 유지, 다음 촉매나 가격 확인 대기"
    return {
        "action": action,
        "recommended_change_pct": recommended_change_pct,
        "recommended_change_band": _change_band(recommended_change_pct),
        "position_intent_ko": intent,
        "reason_bullets": reason_bullets[:5],
        "risk_flags": risk_flags[:8],
    }


def _change_band(change_pct: float) -> str:
    if change_pct <= -99:
        return "100% 축소"
    if change_pct <= -50:
        return "50~70% 축소"
    if change_pct < 0:
        return "20~35% 축소"
    if change_pct >= 20:
        return "10~20% 증액"
    if change_pct > 0:
        return "소폭 증액"
    return "변경 없음"


def _order_draft_preview(sell_first: dict[str, Any], market_data: MarketData) -> dict[str, Any]:
    action = sell_first.get("action")
    change_pct = _safe_float(sell_first.get("recommended_change_pct"), 0.0)
    current_price = _safe_float(getattr(market_data, "current_price", None), 0.0)
    return {
        "advisory_only": True,
        "broker_execution": "not_called",
        "action": action,
        "recommended_change_pct": change_pct,
        "lot_rounding": "whole_share_default",
        "split_plan": {
            "first_leg_pct": 50 if action in {"ADD", "REDUCE", "EXIT"} else 0,
            "second_leg_pct": 50 if action in {"ADD", "REDUCE", "EXIT"} else 0,
            "condition_ko": "1차 실행 후 가격/거래량 확인 시 2차 실행",
        },
        "reference_price": current_price if current_price > 0 else None,
        "note_ko": "실제 주문 API 호출 없이 UI/브로커 모듈이 사용할 주문 초안만 제공합니다.",
    }


def _counter_thesis(direction: str, risk_flags: list[str], market_data: MarketData) -> dict[str, Any]:
    if direction in {"BULLISH", "LONG"}:
        summary = "강세 시나리오의 반대 논리는 초기 갭/호재가 이미 가격에 반영됐고 후속 수급이 약해지는 경우입니다."
        change_mind = ["거래량 감소와 함께 전일 저점 이탈", "RSI 과열 후 MACD 약화", "QQQ/SPY 대비 상대강도 하락"]
    elif direction in {"BEARISH", "SHORT"}:
        summary = "약세 시나리오의 반대 논리는 악재가 선반영됐고 저가 매수와 숏커버가 동시에 유입되는 경우입니다."
        change_mind = ["초기 하락분 회복", "거래량 동반 양봉 전환", "가이던스/뉴스 반박 자료 확인"]
    else:
        summary = "중립 시나리오에서는 가격·거래량·뉴스가 같은 방향으로 정렬되기 전까지 확률 우위가 약합니다."
        change_mind = ["명확한 돌파/이탈", "신규 촉매", "동일 섹터 수급 동조화"]
    chips = list(dict.fromkeys(risk_flags[:5] + _macro_chips(market_data)))[:6]
    return {
        "summary_ko": summary,
        "risk_chips": chips,
        "what_would_change_mind": change_mind,
    }


def _macro_chips(market_data: MarketData) -> list[str]:
    chips: list[str] = []
    vix = _safe_float(getattr(market_data, "vix", None), 18.0)
    if vix >= 25:
        chips.append("high_vix")
    if _safe_float(getattr(market_data, "qqq_relative_strength_20d", None), 0.0) < -2.0:
        chips.append("qqq_relative_weakness")
    if _safe_float(getattr(market_data, "spy_relative_strength_20d", None), 0.0) < -2.0:
        chips.append("spy_relative_weakness")
    return chips


def _feature_driver_chips(market_data: MarketData, analysis: GeminiAnalysisResult, risk_flags: list[str]) -> list[dict[str, Any]]:
    chips: list[dict[str, Any]] = []
    surprise = _safe_float(getattr(market_data, "surprise_pct", None), 0.0)
    if abs(surprise) >= 3.0:
        chips.append({"label_ko": "실적 서프라이즈", "value": round(surprise, 2), "direction": "positive" if surprise > 0 else "negative"})
    volume_ratio = _safe_float(getattr(market_data, "volume_ratio", None), 1.0)
    if volume_ratio >= 1.8:
        chips.append({"label_ko": "거래량 확인", "value": round(volume_ratio, 2), "direction": "positive"})
    rs = _safe_float(getattr(market_data, "relative_strength_20d", None), 0.0)
    if abs(rs) >= 2.0:
        chips.append({"label_ko": "상대강도", "value": round(rs, 2), "direction": "positive" if rs > 0 else "negative"})
    confidence = _safe_float(getattr(analysis, "confidence", None), 0.0)
    chips.append({"label_ko": "모델 확신도", "value": round(confidence, 3), "direction": "positive" if confidence >= 0.65 else "neutral"})
    for flag in risk_flags[:3]:
        chips.append({"label_ko": flag, "value": None, "direction": "risk"})
    return chips[:8]


def build_decision_assistant(
    *,
    market_data: MarketData,
    analysis: GeminiAnalysisResult,
    strategy_decision: StrategyDecision,
    source_type: SourceType,
    signal_explanation: dict[str, Any],
    trade_plan: dict[str, Any] | None = None,
    product_surface: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build additive front/API payloads for actionable buy/sell judgment."""
    metadata = dict(getattr(analysis, "metadata", {}) or {})
    direction = str(getattr(analysis, "direction", "") or "").upper()
    confidence = _safe_float(getattr(analysis, "confidence", None), 0.0)
    magnitude = _safe_float(getattr(analysis, "magnitude", None), 0.0)
    strategy = _strategy_value(strategy_decision)
    actionability_score = _safe_float((product_surface or {}).get("actionability_score"), _safe_float(getattr(strategy_decision, "score", None), 0.0))
    flags = _risk_flags(analysis, strategy_decision)
    for flag in _technical_risk_flags(market_data):
        if flag not in flags:
            flags.append(flag)
    execution = _execution_badge(market_data, flags)
    replay = _replay_confidence_badge(strategy, metadata)
    no_trade = _no_trade_explainer(
        direction=direction,
        risk_flags=flags,
        execution_badge=execution,
        replay_badge=replay,
        signal_explanation=signal_explanation or {},
    )
    sell_first = _sell_first_action(
        direction=direction,
        confidence=confidence,
        magnitude=magnitude,
        actionability_score=actionability_score,
        risk_flags=flags,
        execution_badge=execution,
        no_trade=no_trade,
        replay_badge=replay,
    )
    counter = _counter_thesis(direction, flags, market_data)
    portfolio_impact = _portfolio_impact_map(market_data, flags, direction)
    order_draft = _order_draft_preview(sell_first, market_data)
    driver_chips = _feature_driver_chips(market_data, analysis, flags)
    risk_chips = list(dict.fromkeys(flags + counter.get("risk_chips", [])))[:8]
    badge = "매수 가능" if sell_first["action"] == "ADD" else "매도 우선" if sell_first["action"] in {"REDUCE", "EXIT"} else "진입 보류" if sell_first["action"] == "AVOID" else "관망"
    frontend_cards = {
        "hero": {
            "badge": badge,
            "action": sell_first["action"],
            "reason_summary": sell_first["position_intent_ko"],
            "replay_label": replay.get("label"),
            "execution_label": execution.get("label"),
        },
        "why": {
            "driver_chips": driver_chips,
            "risk_chips": risk_chips,
            "counter_thesis": counter.get("summary_ko"),
        },
        "plan": {
            "order_draft_preview": order_draft,
            "trade_plan": trade_plan or {},
            "portfolio_impact": portfolio_impact,
        },
        "deny_summary": no_trade.get("deny_summary_ko"),
        "driver_chips": driver_chips,
        "risk_chips": risk_chips,
    }
    return {
        "schema_version": _SCHEMA_VERSION,
        "source_type": str(getattr(source_type, "value", source_type)),
        "strategy": strategy,
        "sell_first": sell_first,
        "no_trade_explainer": no_trade,
        "replay_confidence_badge": replay,
        "execution_badge": execution,
        "counter_thesis": counter,
        "portfolio_impact_map": portfolio_impact,
        "order_draft_preview": order_draft,
        "strategy_leaderboard_hint": {
            "strategy": strategy,
            "current_validated_track": replay.get("source_artifact"),
            "label": replay.get("label"),
            "promotion_note_ko": "검증 배지는 실제 replay/proxy artifact와 분리해 표시하며, live 주문 실행을 의미하지 않습니다.",
        },
        "frontend_cards": frontend_cards,
    }


__all__ = ["build_decision_assistant"]
