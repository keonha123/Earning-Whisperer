"""Signal Brief builders for frontend/API-safe action summaries."""

from __future__ import annotations

from typing import Any


def _action_from_direction(direction: str | None, *, execution_allowed: bool, decision_state: str | None) -> str:
    normalized = str(direction or "").upper()
    if not execution_allowed:
        return "AVOID"
    if normalized in {"BULLISH", "LONG"}:
        return "BUY"
    if normalized in {"BEARISH", "SHORT"}:
        return "SELL"
    if str(decision_state or "").lower() == "review":
        return "HOLD"
    return "HOLD"


def _gate_result(*, execution_allowed: bool, blocked_reasons: dict[str, Any], review_triggered: bool) -> str:
    gate_rejections = blocked_reasons.get("gate_rejections") or []
    control_blocks = blocked_reasons.get("control_blocks") or []
    risk_overrides = blocked_reasons.get("risk_overrides") or []
    if gate_rejections:
        return "hard_block"
    if control_blocks or risk_overrides:
        return "soft_block"
    if review_triggered and execution_allowed:
        return "review_required"
    return "pass"


def _ensure_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if value is not None][:5]


def build_signal_brief(
    *,
    analysis: dict[str, Any],
    analysis_object: dict[str, Any],
    product_surface: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signal_explanation = analysis_object.get("signal_explanation") if isinstance(analysis_object.get("signal_explanation"), dict) else {}
    execution_allowed = bool(analysis.get("execution_allowed", True))
    decision_state = analysis.get("decision_state") or signal_explanation.get("decision_state") or "tradable"
    blocked_reasons = signal_explanation.get("blocked_reasons") if isinstance(signal_explanation.get("blocked_reasons"), dict) else {}
    reasons = _ensure_list(signal_explanation.get("reasons") or signal_explanation.get("top_drivers"))
    risks = _ensure_list(signal_explanation.get("risks") or signal_explanation.get("top_risks"))
    frontend_payload = signal_explanation.get("frontend_payload_ko") if isinstance(signal_explanation.get("frontend_payload_ko"), dict) else {}
    actionability_score = None
    institutional_edge = None
    decision_assistant = None
    if isinstance(product_surface, dict):
        try:
            actionability_score = float(product_surface.get("actionability_score"))
        except (TypeError, ValueError):
            actionability_score = None
        if isinstance(product_surface.get("institutional_edge"), dict):
            institutional_edge = product_surface.get("institutional_edge")
        if isinstance(product_surface.get("decision_assistant"), dict):
            decision_assistant = product_surface.get("decision_assistant")

    brief = {
        "action": _action_from_direction(
            analysis_object.get("direction"),
            execution_allowed=execution_allowed,
            decision_state=decision_state,
        ),
        "confidence": analysis_object.get("confidence"),
        "summary_ko": signal_explanation.get("summary_ko") or frontend_payload.get("summary") or analysis.get("signal_explanation"),
        "key_reasons_ko": reasons,
        "risk_flags_ko": risks,
        "recommended_hold_days": (analysis_object.get("strategy_decision") or {}).get("hold_days") or analysis.get("hold_days") or 1,
        "gate_result": _gate_result(
            execution_allowed=execution_allowed,
            blocked_reasons=blocked_reasons,
            review_triggered=bool(analysis.get("review_triggered")),
        ),
        "model_version": analysis.get("model_version"),
        "strategy_id": (analysis_object.get("strategy_decision") or {}).get("strategy") or analysis.get("strategy"),
        "decision_state": decision_state,
        "blocked_reason_ko": analysis.get("blocked_reason_ko"),
        "action_label_ko": frontend_payload.get("direction"),
        "actionability_score": actionability_score,
        "badge": frontend_payload.get("badge"),
    }
    if isinstance(institutional_edge, dict):
        brief["institutional_grade"] = institutional_edge.get("grade")
        brief["institutional_grade_score"] = institutional_edge.get("institutional_grade_score")
        brief["institutional_approval_state"] = institutional_edge.get("approval_state")
    if isinstance(decision_assistant, dict):
        sell_first = decision_assistant.get("sell_first") if isinstance(decision_assistant.get("sell_first"), dict) else {}
        no_trade = decision_assistant.get("no_trade_explainer") if isinstance(decision_assistant.get("no_trade_explainer"), dict) else {}
        counter = decision_assistant.get("counter_thesis") if isinstance(decision_assistant.get("counter_thesis"), dict) else {}
        brief["sell_first_action"] = sell_first.get("action")
        brief["recommended_change_pct"] = sell_first.get("recommended_change_pct")
        brief["position_intent_ko"] = sell_first.get("position_intent_ko")
        brief["no_trade_summary_ko"] = no_trade.get("deny_summary_ko")
        brief["replay_confidence_badge"] = decision_assistant.get("replay_confidence_badge")
        brief["execution_badge"] = decision_assistant.get("execution_badge")
        brief["counter_thesis_ko"] = counter.get("summary_ko")
        if no_trade.get("blocked") and brief.get("action") in {"BUY", "SELL"}:
            brief["action"] = "AVOID"
            brief["gate_result"] = "soft_block"
    return brief


def apply_runtime_to_signal_brief(signal_brief: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(signal_brief, dict):
        return signal_brief
    updated = dict(signal_brief)
    execution_allowed = bool(runtime.get("execution_allowed", True))
    updated["decision_state"] = runtime.get("decision_state", updated.get("decision_state"))
    updated["blocked_reason_ko"] = runtime.get("blocked_reason_ko")
    updated["gate_result"] = _gate_result(
        execution_allowed=execution_allowed,
        blocked_reasons=runtime.get("blocked_reasons") if isinstance(runtime.get("blocked_reasons"), dict) else {},
        review_triggered=updated.get("gate_result") == "review_required",
    )
    if not execution_allowed and updated.get("action") in {"BUY", "SELL"}:
        updated["action"] = "AVOID"
    return updated


__all__ = ["apply_runtime_to_signal_brief", "build_signal_brief"]
