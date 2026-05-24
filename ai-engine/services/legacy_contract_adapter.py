"""Adapters between the original GitHub AI-engine contract and v9 envelopes."""

from __future__ import annotations

from typing import Any

try:
    from core.investment_profiles import build_strategy_recommendation, profile_action_from_score, resolve_investment_profile
    from models.legacy_contract_models import LegacyAnalyzeRequest, LegacySignalMessage
    from models.request_models import AnalyzeRequest, MarketData, SectionType, SourceType
except ImportError:  # pragma: no cover
    from ..core.investment_profiles import build_strategy_recommendation, profile_action_from_score, resolve_investment_profile
    from ..models.legacy_contract_models import LegacyAnalyzeRequest, LegacySignalMessage
    from ..models.request_models import AnalyzeRequest, MarketData, SectionType, SourceType


def _enum_or_default(enum_type: type[SectionType] | type[SourceType], value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return enum_type(str(value).upper())
    except ValueError:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _signed_raw_score(analysis: dict[str, Any]) -> float:
    raw_score = analysis.get("raw_score")
    if raw_score is not None:
        return _clamp(_safe_float(raw_score))

    direction = str(analysis.get("direction") or "").upper()
    magnitude = abs(_safe_float(analysis.get("magnitude"), 0.0))
    if direction in {"BULLISH", "LONG", "BUY"}:
        return _clamp(magnitude)
    if direction in {"BEARISH", "SHORT", "SELL"}:
        return _clamp(-magnitude)
    return 0.0


def _action_from_score(raw_score: float) -> str:
    if raw_score > 0.05:
        return "BUY"
    if raw_score < -0.05:
        return "SELL"
    return "HOLD"


class LegacyContractAdapter:
    """Converts legacy payloads into v9 requests and v9 envelopes back to legacy signals."""

    @staticmethod
    def to_analyze_request(payload: LegacyAnalyzeRequest) -> AnalyzeRequest:
        market_data = dict(payload.market_data or {})
        market_data.setdefault("ticker", payload.ticker)
        return AnalyzeRequest(
            ticker=payload.ticker,
            prompt=payload.text_chunk,
            market_data=MarketData.model_validate(market_data),
            section_type=_enum_or_default(SectionType, payload.section_type, SectionType.UNKNOWN),
            source_type=_enum_or_default(SourceType, payload.source_type, SourceType.EARNINGS_CALL),
            chunk_sequence=payload.sequence,
            request_priority=payload.request_priority,
            is_final=payload.is_final,
            route_profile=payload.route_profile,
            needs_review=payload.needs_review,
            universe_profile=payload.universe_profile,
            investment_profile=payload.investment_profile,
            request_metadata={
                "legacy_contract": True,
                "investment_profile": payload.investment_profile,
                "original_timestamp": payload.timestamp,
                "original_sequence": payload.sequence,
                "original_text_chunk": payload.text_chunk,
            },
        )

    @staticmethod
    def to_legacy_signal(payload: LegacyAnalyzeRequest, envelope: dict[str, Any]) -> LegacySignalMessage:
        analysis = envelope.get("analysis") if isinstance(envelope.get("analysis"), dict) else {}
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
        event = data.get("event") if isinstance(data.get("event"), dict) else {}
        signal_brief = envelope.get("signal_brief") if isinstance(envelope.get("signal_brief"), dict) else data.get("signal_brief")
        raw_score = _signed_raw_score(analysis)
        metadata = analysis.get("metadata") if isinstance(analysis.get("metadata"), dict) else {}
        profile_meta = metadata.get("investment_profile") if isinstance(metadata.get("investment_profile"), dict) else None
        profile = resolve_investment_profile(payload.investment_profile)
        if profile is None and isinstance(profile_meta, dict):
            profile = resolve_investment_profile(str(profile_meta.get("code") or ""))
        action = profile_action_from_score(raw_score, profile) if profile is not None else _action_from_score(raw_score)
        strategy_recommendation = (
            build_strategy_recommendation(
                profile,
                strategy=analysis.get("strategy") or envelope.get("strategy"),
                action=action,
                confidence=_safe_float(analysis.get("confidence")) if analysis.get("confidence") is not None else None,
                hold_days=_safe_int(analysis.get("hold_days"), 0) or None,
                risk_flags=list(analysis.get("risk_flags") or []),
            )
            if profile is not None
            else None
        )
        return LegacySignalMessage(
            ticker=payload.ticker,
            raw_score=raw_score,
            rationale=str(analysis.get("rationale") or "No rationale provided."),
            text_chunk=payload.text_chunk,
            timestamp=_safe_int(payload.timestamp),
            is_session_end=bool(payload.is_final),
            action=action,
            confidence=_safe_float(analysis.get("confidence")) if analysis.get("confidence") is not None else None,
            strategy=analysis.get("strategy") or envelope.get("strategy"),
            hold_days=_safe_int(analysis.get("hold_days"), 0) or None,
            model_route=analysis.get("model_route") or analysis.get("model_version"),
            execution_allowed=analysis.get("execution_allowed"),
            blocked_reason_ko=analysis.get("blocked_reason_ko"),
            signal_brief=signal_brief if isinstance(signal_brief, dict) else None,
            engine_event_id=event.get("event_id") if isinstance(event, dict) else None,
            investment_profile=profile.code if profile is not None else None,
            investment_profile_label_ko=profile.label_ko if profile is not None else None,
            universe_profile=profile.universe_profile if profile is not None else None,
            risk_style=profile.risk_style if profile is not None else None,
            redis_output_profile=profile.redis_output_profile if profile is not None else None,
            strategy_recommendation=strategy_recommendation,
        )

    @staticmethod
    def build_enriched_message(legacy_signal: LegacySignalMessage, envelope: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "2026-05-13.enriched-ai-signal-v1",
            "legacy_signal": legacy_signal.model_dump(mode="json", exclude_none=True),
            "engine_envelope": envelope,
        }


__all__ = ["LegacyContractAdapter"]
