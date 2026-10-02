"""Runtime dispatch helpers for AI engine analysis responses."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

try:
    from config import Settings
    from core.event_payload_builder import build_engine_event_response
    from core.signal_brief import apply_runtime_to_signal_brief
    from models.request_models import AnalyzeRequest
    from services.control_plane_service import ControlPlaneService
except ImportError:  # pragma: no cover
    from ..config import Settings
    from ..core.event_payload_builder import build_engine_event_response
    from ..core.signal_brief import apply_runtime_to_signal_brief
    from ..models.request_models import AnalyzeRequest
    from .control_plane_service import ControlPlaneService


AnalyzeRunner = Callable[..., Awaitable[Any]]
logger = logging.getLogger(__name__)


def _unavailable_controls() -> dict[str, Any]:
    reason = "실행 제어 상태를 확인할 수 없어 실행을 차단했습니다. 분석은 참고용으로만 제공됩니다."
    return {
        "execution_allowed": False,
        "blocked_reason_ko": reason,
        "decision_state": "blocked",
        "control_overrides": [],
        "gate_failures": [],
        "blocked_reasons": {
            "gate_rejections": [], "risk_overrides": [],
            "control_blocks": [{"type": "runtime_controls_unavailable", "reason_ko": reason}],
        },
        "active_patch_id": None,
        "rollout_bucket": None,
        "calibration_segment": None,
    }


def _apply_runtime_overlay(
    *,
    analysis: dict[str, Any],
    envelope: dict[str, Any],
    runtime: dict[str, Any],
) -> None:
    analysis["execution_allowed"] = runtime["execution_allowed"]
    analysis["blocked_reason_ko"] = runtime["blocked_reason_ko"]
    analysis["decision_state"] = runtime["decision_state"]
    analysis["control_overrides"] = runtime["control_overrides"]

    metadata = analysis.setdefault("metadata", {})
    metadata["active_patch_id"] = runtime["active_patch_id"]
    metadata["rollout_bucket"] = runtime["rollout_bucket"]
    metadata["calibration_segment"] = runtime["calibration_segment"]

    signal_explanation = metadata.setdefault("signal_explanation", {})
    signal_explanation["gate_failures"] = runtime["gate_failures"]
    signal_explanation["blocked_reasons"] = runtime["blocked_reasons"]
    signal_explanation["decision_state"] = runtime["decision_state"]
    signal_explanation["control_overrides"] = runtime["control_overrides"]
    signal_explanation["calibration_segment"] = runtime["calibration_segment"]
    signal_explanation["active_patch_id"] = runtime["active_patch_id"]
    signal_explanation["rollout_bucket"] = runtime["rollout_bucket"]

    frontend_payload = signal_explanation.setdefault("frontend_payload_ko", {})
    frontend_payload["deny_summary"] = runtime["blocked_reason_ko"]
    frontend_payload["badge"] = "blocked" if not runtime["execution_allowed"] else frontend_payload.get("badge", "tradable")
    frontend_payload["reason_summary"] = frontend_payload.get("reason_summary") or frontend_payload.get("summary")
    frontend_payload["driver_chips"] = frontend_payload.get("driver_chips") or signal_explanation.get("top_drivers") or []
    frontend_payload["risk_chips"] = frontend_payload.get("risk_chips") or signal_explanation.get("top_risks") or []

    analysis_view = envelope.get("data", {}).get("analysis", {})
    signal_view = analysis_view.get("signal_explanation", {})
    signal_view.update(
        {
            "gate_failures": runtime["gate_failures"],
            "blocked_reasons": runtime["blocked_reasons"],
            "decision_state": runtime["decision_state"],
            "control_overrides": runtime["control_overrides"],
            "calibration_segment": runtime["calibration_segment"],
            "active_patch_id": runtime["active_patch_id"],
            "rollout_bucket": runtime["rollout_bucket"],
            "feature_contributions": signal_explanation.get("feature_contributions") or [],
            "top_drivers": signal_explanation.get("top_drivers") or [],
            "top_risks": signal_explanation.get("top_risks") or [],
        }
    )

    for card in envelope.get("data", {}).get("cards", []):
        payload_block = card.get("payload") if isinstance(card.get("payload"), dict) else None
        if not payload_block:
            continue
        if card.get("card_type") == "hero_decision":
            payload_block["decision_state"] = runtime["decision_state"]
            payload_block["execution_allowed"] = runtime["execution_allowed"]
            payload_block["deny_summary"] = runtime["blocked_reason_ko"]
            payload_block["driver_chips"] = frontend_payload.get("driver_chips") or []
            payload_block["risk_chips"] = frontend_payload.get("risk_chips") or []
            payload_block["rollout_bucket"] = runtime["rollout_bucket"]
            payload_block["active_patch_id"] = runtime["active_patch_id"]
        elif card.get("card_type") == "why":
            payload_block["feature_contributions"] = signal_explanation.get("feature_contributions") or []
            payload_block["blocked_reasons"] = runtime["blocked_reasons"]
        elif card.get("card_type") == "trade_plan":
            payload_block["execution_allowed"] = runtime["execution_allowed"]
            payload_block["blocked_reason_ko"] = runtime["blocked_reason_ko"]

    if isinstance(envelope.get("signal_brief"), dict):
        envelope["signal_brief"] = apply_runtime_to_signal_brief(envelope["signal_brief"], runtime)
    data_signal_brief = envelope.get("data", {}).get("signal_brief")
    if isinstance(data_signal_brief, dict):
        envelope["data"]["signal_brief"] = apply_runtime_to_signal_brief(data_signal_brief, runtime)

    if not runtime["execution_allowed"]:
        display = apply_runtime_to_signal_brief({}, runtime)
        signal_explanation["summary_ko"] = display["summary_ko"]
        signal_view["summary_ko"] = display["summary_ko"]
        frontend_payload["summary"] = display["summary_ko"]
        for card in envelope.get("data", {}).get("cards", []):
            card_payload = card.get("payload")
            if not isinstance(card_payload, dict):
                continue
            if card.get("card_type") == "hero_decision":
                card_payload.update(decision="AVOID", decision_label_ko="진입 보류",
                                    badge="blocked", summary=display["summary_ko"])
            elif card.get("card_type") == "decision_assistant":
                card_payload["badge"] = "blocked"
                card_payload["execution_badge"] = apply_runtime_to_signal_brief(
                    {"execution_badge": card_payload.get("execution_badge")}, runtime
                )["execution_badge"]


async def dispatch_analysis(
    *,
    payload: AnalyzeRequest,
    settings: Settings,
    analysis_runner: AnalyzeRunner,
    control_service: ControlPlaneService | None = None,
) -> dict[str, Any]:
    requested_route = payload.route_profile or ("review" if payload.needs_review else "economy")
    result = await analysis_runner(
        ticker=payload.ticker,
        current_chunk=payload.current_chunk,
        market_data=payload.market_data,
        section_type=payload.section_type,
        source_type=payload.source_type,
        chunk_sequence=payload.chunk_sequence,
        request_priority=payload.request_priority,
        is_final=payload.is_final,
        route_profile=requested_route,
        universe_profile=payload.universe_profile,
        canonical_bundle=payload.canonical_bundle,
        source_health=payload.source_health,
        evidence_documents=payload.evidence_documents,
        request_metadata=payload.request_metadata,
    )
    analysis = result.model_dump()
    analysis.setdefault(
        "model_version",
        settings.gemini_review_model if (payload.needs_review or requested_route == "review") else settings.gemini_primary_model,
    )
    analysis.setdefault("review_triggered", bool(payload.needs_review or requested_route == "review"))

    envelope = build_engine_event_response(payload=payload, analysis=analysis)
    if settings.runtime_controls_mode == "offline":
        analysis.setdefault("metadata", {})["runtime_controls"] = {"status": "offline", "verified": False}
    else:
        try:
            if control_service is None:
                raise RuntimeError("Runtime control service is not configured")
            runtime = await asyncio.to_thread(
                control_service.apply_runtime_controls,
                payload=payload,
                analysis=analysis,
                event_id=envelope.get("data", {}).get("event", {}).get("event_id"),
            )
            if not isinstance(runtime, dict):
                raise RuntimeError("Runtime control service returned no decision")
            analysis.setdefault("metadata", {})["runtime_controls"] = {"status": "verified", "verified": True}
        except Exception:
            logger.warning("Runtime controls unavailable; execution blocked", exc_info=True)
            runtime = _unavailable_controls()
            analysis.setdefault("metadata", {})["runtime_controls"] = {"status": "unavailable", "verified": False}
        _apply_runtime_overlay(analysis=analysis, envelope=envelope, runtime=runtime)

    envelope.update(
        {
            "analysis": analysis,
            "strategy": analysis.get("strategy", "SENTIMENT_ONLY"),
            "metadata": analysis.get("metadata", {}),
        }
    )
    return envelope


__all__ = ["dispatch_analysis"]
