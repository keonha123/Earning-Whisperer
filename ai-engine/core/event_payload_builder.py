from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from models.request_models import AnalyzeRequest, MarketData, SourceType
    from core.signal_brief import build_signal_brief
except ImportError:  # pragma: no cover
    from ..models.request_models import AnalyzeRequest, MarketData, SourceType
    from .signal_brief import build_signal_brief

_SCHEMA_VERSION = "2026-04-19.ai-engine-event-v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str | None) -> str:
    if not value:
        return "unknown"
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_") or "unknown"


def _quarter_code(ts: datetime) -> str:
    return f"{ts.year}q{((ts.month - 1) // 3) + 1}"


def _market_session_from_source(source_type: str | None) -> str:
    if source_type == SourceType.EARNINGS_CALL.value:
        return "post_market"
    if source_type == SourceType.NEWS.value:
        return "intraday"
    return "unknown"


def _build_request_id(ts: datetime, payload: AnalyzeRequest) -> str:
    return f"req_{_slug(payload.ticker)}_{ts.strftime('%Y%m%dT%H%M%SZ')}_{payload.chunk_sequence:03d}"


def _build_event_id(ts: datetime, payload: AnalyzeRequest) -> str:
    source = _slug(payload.source_type.value.lower())
    if payload.source_type == SourceType.EARNINGS_CALL:
        return f"evt_{_slug(payload.ticker)}_{_quarter_code(ts)}_{payload.chunk_sequence:03d}"
    return f"evt_{_slug(payload.ticker)}_{source}_{ts.strftime('%Y%m%d')}_{payload.chunk_sequence:03d}"


def _strategy_label_ko(strategy: str | None) -> str:
    mapping = {
        "PEAD": "실적발표 후 드리프트 지속",
        "GAP_AND_GO": "갭 상승 지속",
        "GAP_FILL": "갭 메우기 역추세",
        "REVERSAL_CATALYST": "반전 촉매",
        "IV_CRUSH_DECAY": "변동성 축소",
        "SHORT_SQUEEZE": "숏스퀴즈 지속",
        "WHISPER_PLAY": "위스퍼 상회 돌파",
        "NEWS_BREAKOUT": "뉴스 돌파",
        "MOMENTUM_CARRY": "모멘텀 캐리",
        "SENTIMENT_ONLY": "단기 센티먼트",
        "ERROR_FALLBACK": "오류 대체 전략",
    }
    return mapping.get(str(strategy or "").upper(), str(strategy or "전략 미정"))


def _entry_style_label_ko(entry_style: str | None) -> str:
    mapping = {
        "buy_pullback_or_breakout": "눌림 또는 돌파 확인 진입",
        "sell_rip_or_breakdown": "반등 매도 또는 하향 이탈 진입",
        "fade_extension_after_rejection": "과열 후 밀림 확인 진입",
        "buy_flush_after_stabilization": "급락 후 안정화 확인 진입",
        "event_passed_wait_for_vol_compression": "이벤트 후 변동성 축소 대기",
        "no_trade_or_micro_size": "관망 또는 극소형 진입",
    }
    return mapping.get(str(entry_style or ""), "상황 확인 후 진입")


def _decision_code(direction: str | None, confidence: float | None, actionability_score: float | None) -> str:
    confidence = float(confidence or 0.0)
    actionability_score = float(actionability_score or 0.0)
    if confidence < 0.4 and actionability_score < 0.45:
        return "watch"
    if str(direction).upper() in {"BULLISH", "LONG"}:
        return "long_candidate"
    if str(direction).upper() in {"BEARISH", "SHORT"}:
        return "short_candidate"
    return "neutral"


def _decision_label_ko(code: str) -> str:
    mapping = {
        "long_candidate": "Long 후보",
        "short_candidate": "Short 후보",
        "watch": "관찰",
        "neutral": "중립",
    }
    return mapping.get(code, "중립")


def _confidence_badge(confidence: float | None, actionability_score: float | None) -> str:
    confidence = float(confidence or 0.0)
    actionability_score = float(actionability_score or 0.0)
    score = 0.55 * confidence + 0.45 * actionability_score
    if score >= 0.8:
        return "고확신"
    if score >= 0.62:
        return "중확신"
    return "관찰"


def _topic_deltas(metadata: dict[str, Any]) -> dict[str, float]:
    transcript_signals = metadata.get("transcript_signals") if isinstance(metadata, dict) else None
    topic_deltas = transcript_signals.get("topic_deltas") if isinstance(transcript_signals, dict) else {}
    return {
        "guidance_delta": round(float(topic_deltas.get("guidance", 0.0) or 0.0), 4),
        "demand_delta": round(float(topic_deltas.get("demand", 0.0) or 0.0), 4),
        "margin_delta": round(float(topic_deltas.get("margin", 0.0) or 0.0), 4),
        "capex_delta": round(float(topic_deltas.get("capex", 0.0) or 0.0), 4),
        "management_confidence": round(float(transcript_signals.get("confidence_signal", 0.0) or 0.0), 4) if isinstance(transcript_signals, dict) else 0.0,
        "qa_evasiveness": round(float(transcript_signals.get("evasion_score", 0.0) or 0.0), 4) if isinstance(transcript_signals, dict) else 0.0,
        "contradiction_score": round(abs(float(transcript_signals.get("contradiction_penalty", 0.0) or 0.0)), 4) if isinstance(transcript_signals, dict) else 0.0,
    }


def _build_event_summary(*, event_id: str, ts: datetime, payload: AnalyzeRequest, metadata: dict[str, Any]) -> dict[str, Any]:
    company_name = metadata.get("company_name") or payload.ticker
    sector = metadata.get("sector") or None
    return {
        "event_id": event_id,
        "ticker": payload.ticker,
        "company_name": company_name,
        "event_type": payload.source_type.value.lower(),
        "event_time": _iso(ts),
        "market_session": _market_session_from_source(payload.source_type.value),
        "sector": sector,
        "schema_version": _SCHEMA_VERSION,
    }


def _build_market_snapshot(market_data: MarketData) -> dict[str, Any]:
    return {
        "current_price": _safe_float(market_data.current_price),
        "gap_pct": _safe_float(market_data.gap_pct),
        "surprise_pct": _safe_float(market_data.surprise_pct),
        "volume_ratio": _safe_float(market_data.volume_ratio),
        "sector_momentum": _safe_float(market_data.sector_momentum),
        "iv_rank": _safe_float(market_data.iv_rank),
        "vix": _safe_float(market_data.vix),
        "implied_move_pct": _safe_float(market_data.implied_move_pct),
        "rsi_14": _safe_float(market_data.rsi_14),
        "liquidity_score": _safe_float(market_data.liquidity_score),
        "relative_strength_20d": _safe_float(market_data.relative_strength_20d),
        "atr_pct_14": _safe_float(market_data.atr_pct_14),
        "market_cap": _safe_float(market_data.market_cap),
        "market_cap_bucket": market_data.market_cap_bucket,
        "sector_code": market_data.sector_code,
    }


def _derive_counter_scenario(direction: str | None, trade_plan: dict[str, Any], risks: list[str]) -> str:
    stop_loss = trade_plan.get("stop_loss") if isinstance(trade_plan, dict) else None
    if str(direction).upper() in {"BULLISH", "LONG"}:
        base = "초기 강세가 유지되지 않고 눌림 이후 회복에 실패하면 추세 지속 확률이 낮아질 수 있습니다."
    elif str(direction).upper() in {"BEARISH", "SHORT"}:
        base = "초기 약세가 이어지지 않고 빠르게 되돌림이 나오면 하락 추세 시나리오가 약해질 수 있습니다."
    else:
        base = "가격 반응이 중립적으로 굳어지면 명확한 방향성 시나리오는 약해질 수 있습니다."
    if stop_loss is not None:
        base += f" 손절 기준은 {stop_loss} 부근입니다."
    if risks:
        base += f" 주요 리스크는 {risks[0]}입니다."
    return base


def _build_analysis_object(analysis: dict[str, Any], market_data: MarketData) -> dict[str, Any]:
    metadata = analysis.get("metadata") if isinstance(analysis.get("metadata"), dict) else {}
    signal_explanation = metadata.get("signal_explanation") if isinstance(metadata, dict) and isinstance(metadata.get("signal_explanation"), dict) else {}
    trade_plan = metadata.get("trade_plan") if isinstance(metadata, dict) and isinstance(metadata.get("trade_plan"), dict) else {}
    feature_bundle = metadata.get("feature_bundle") if isinstance(metadata, dict) and isinstance(metadata.get("feature_bundle"), dict) else {}
    signal_data_hub = metadata.get("signal_data_hub") if isinstance(metadata, dict) and isinstance(metadata.get("signal_data_hub"), dict) else {}
    institutional_edge = metadata.get("institutional_edge") if isinstance(metadata, dict) and isinstance(metadata.get("institutional_edge"), dict) else {}
    decision_assistant = metadata.get("decision_assistant") if isinstance(metadata, dict) and isinstance(metadata.get("decision_assistant"), dict) else {}
    historical_transcript_diff = metadata.get("historical_transcript_diff") if isinstance(metadata, dict) and isinstance(metadata.get("historical_transcript_diff"), dict) else {}
    if not decision_assistant and isinstance(metadata.get("product_surface"), dict):
        product_decision_assistant = metadata["product_surface"].get("decision_assistant")
        if isinstance(product_decision_assistant, dict):
            decision_assistant = product_decision_assistant
    strategy = analysis.get("strategy")
    reasons = list(dict.fromkeys((signal_explanation.get("key_factors_ko") or []) + (signal_explanation.get("transcript_modifiers_ko") or [])))[:5]
    risks = list(dict.fromkeys(signal_explanation.get("counterfactors_ko") or []))[:5]
    return {
        "direction": analysis.get("direction"),
        "magnitude": _safe_float(analysis.get("magnitude")),
        "confidence": _safe_float(analysis.get("confidence")),
        "catalyst_type": analysis.get("catalyst_type"),
        "strategy_decision": {
            "strategy": strategy,
            "score": _safe_float((metadata.get("strategy_score") if isinstance(metadata, dict) else None) or (signal_explanation.get("frontend_payload_ko") or {}).get("score")),
            "hold_days": _safe_int(analysis.get("hold_days")) or 1,
            "rationale": analysis.get("rationale"),
            "risk_flags": analysis.get("risk_flags") or [],
        },
        "signal_explanation": {
            "display_text": signal_explanation.get("display_text") or analysis.get("signal_explanation"),
            "summary_ko": signal_explanation.get("summary_ko"),
            "reasons": reasons,
            "risks": risks,
            "counter_scenario": _derive_counter_scenario(analysis.get("direction"), trade_plan, risks),
            "hold_period_reason": signal_explanation.get("hold_period_reason_ko") or analysis.get("hold_days_reason"),
            "feature_contributions": signal_explanation.get("feature_contributions") or [],
            "top_drivers": signal_explanation.get("top_drivers") or [],
            "top_risks": signal_explanation.get("top_risks") or [],
            "gate_failures": signal_explanation.get("gate_failures") or [],
            "blocked_reasons": signal_explanation.get("blocked_reasons") or {},
            "decision_state": signal_explanation.get("decision_state"),
            "control_overrides": signal_explanation.get("control_overrides") or [],
            "calibration_segment": signal_explanation.get("calibration_segment"),
            "active_patch_id": signal_explanation.get("active_patch_id"),
            "rollout_bucket": signal_explanation.get("rollout_bucket"),
        },
        "topic_deltas": _topic_deltas(metadata),
        "feature_bundle": feature_bundle,
        "signal_data_hub": signal_data_hub,
        "institutional_edge": institutional_edge,
        "decision_assistant": decision_assistant,
        "historical_transcript_diff": historical_transcript_diff,
    }


def _build_hero_card(event: dict[str, Any], analysis_object: dict[str, Any], product_surface: dict[str, Any], signal_explanation: dict[str, Any]) -> dict[str, Any]:
    frontend = product_surface.get("frontend_contract_ko") if isinstance(product_surface, dict) else {}
    hero = frontend.get("hero") if isinstance(frontend, dict) and isinstance(frontend.get("hero"), dict) else {}
    cta_block = frontend.get("cta") if isinstance(frontend, dict) and isinstance(frontend.get("cta"), dict) else {}
    cta = cta_block.get("primary") if isinstance(cta_block.get("primary"), dict) else {}
    decision = _decision_code(
        analysis_object.get("direction"),
        analysis_object.get("confidence"),
        product_surface.get("actionability_score") if isinstance(product_surface, dict) else None,
    )
    summary_ko = analysis_object.get("signal_explanation", {}).get("summary_ko")
    reasons = analysis_object.get("signal_explanation", {}).get("reasons") or []
    headline = reasons[0] if reasons else (hero.get("title") or "실적 이벤트 판단")
    return {
        "card_id": f"card_hero_{event['event_id']}",
        "card_type": "hero_decision",
        "priority": 1,
        "visible": True,
        "locked": False,
        "payload": {
            "ticker": event.get("ticker"),
            "company_name": event.get("company_name"),
            "decision": decision,
            "decision_label_ko": _decision_label_ko(decision),
            "badge": _confidence_badge(analysis_object.get("confidence"), product_surface.get("actionability_score") if isinstance(product_surface, dict) else None),
            "headline": headline,
            "summary": summary_ko,
            "confidence": analysis_object.get("confidence"),
            "cta": {
                "action_code": cta.get("action_code") or "open_trade_card",
                "label": cta.get("label") or "전략 카드 열기",
            },
        },
    }


def _build_why_card(event: dict[str, Any], analysis_object: dict[str, Any]) -> dict[str, Any]:
    explanation = analysis_object.get("signal_explanation", {})
    return {
        "card_id": f"card_why_{event['event_id']}",
        "card_type": "why",
        "priority": 2,
        "visible": True,
        "locked": False,
        "payload": {
            "title": "왜 이런 시그널이 나왔나",
            "reasons": explanation.get("reasons") or [],
            "risks": explanation.get("risks") or [],
            "counter_scenario": explanation.get("counter_scenario"),
        },
    }


def _build_trade_card(event: dict[str, Any], analysis: dict[str, Any], product_surface: dict[str, Any]) -> dict[str, Any]:
    metadata = analysis.get("metadata") if isinstance(analysis.get("metadata"), dict) else {}
    trade_plan = metadata.get("trade_plan") if isinstance(metadata, dict) and isinstance(metadata.get("trade_plan"), dict) else {}
    primary_surface = product_surface.get("recommended_primary_surface") if isinstance(product_surface, dict) else None
    locked = primary_surface in {"decision_unlock", "pro_subscription", "power_subscription"}
    time_stop_days = trade_plan.get("time_stop_days") or analysis.get("hold_days") or 1
    stop_loss = trade_plan.get("stop_loss")
    invalidation = f"{stop_loss} 이탈 시 시나리오 약화" if stop_loss is not None else "핵심 지지/저항 이탈 시 시나리오 약화"
    notes = trade_plan.get("execution_notes") or []
    sizing_hint = trade_plan.get("sizing_hint") or "full_size"
    return {
        "card_id": f"card_trade_{event['event_id']}",
        "card_type": "trade_plan",
        "priority": 3,
        "visible": True,
        "locked": locked,
        "payload": {
            "strategy": analysis.get("strategy"),
            "strategy_label_ko": _strategy_label_ko(analysis.get("strategy")),
            "hold_days": analysis.get("hold_days") or 1,
            "entry_style": trade_plan.get("entry_style") or "no_trade_or_micro_size",
            "entry_style_label_ko": _entry_style_label_ko(trade_plan.get("entry_style")),
            "invalidation": invalidation,
            "time_stop": f"D+{time_stop_days} 종가 기준 재평가",
            "positioning_note": (notes[0] if notes else "시가 추격보다 확인 후 진입이 유리") + f" / {sizing_hint}",
            "entry_zone": trade_plan.get("entry_zone"),
            "take_profit_1": trade_plan.get("take_profit_1"),
            "take_profit_2": trade_plan.get("take_profit_2"),
        },
        "lock_context": {
            "paywall_type": primary_surface or "decision_unlock",
            "message": "전략, 보유기간 이유, 무효화 조건은 unlock 후 확인할 수 있습니다.",
        } if locked else None,
    }


def _build_risk_card(event: dict[str, Any], analysis_object: dict[str, Any]) -> dict[str, Any] | None:
    risks = analysis_object.get("signal_explanation", {}).get("risks") or []
    if not risks:
        return None
    return {
        "card_id": f"card_risk_{event['event_id']}",
        "card_type": "risk_warning",
        "priority": 4,
        "visible": True,
        "locked": False,
        "payload": {
            "title": "주의해야 할 리스크",
            "items": risks,
        },
    }


def _build_decision_assistant_card(event: dict[str, Any], analysis_object: dict[str, Any]) -> dict[str, Any] | None:
    decision_assistant = analysis_object.get("decision_assistant")
    if not isinstance(decision_assistant, dict) or not decision_assistant:
        return None
    frontend = decision_assistant.get("frontend_cards") if isinstance(decision_assistant.get("frontend_cards"), dict) else {}
    hero = frontend.get("hero") if isinstance(frontend.get("hero"), dict) else {}
    why = frontend.get("why") if isinstance(frontend.get("why"), dict) else {}
    plan = frontend.get("plan") if isinstance(frontend.get("plan"), dict) else {}
    sell_first = decision_assistant.get("sell_first") if isinstance(decision_assistant.get("sell_first"), dict) else {}
    no_trade = decision_assistant.get("no_trade_explainer") if isinstance(decision_assistant.get("no_trade_explainer"), dict) else {}
    return {
        "card_id": f"card_decision_assistant_{event['event_id']}",
        "card_type": "decision_assistant",
        "priority": 4,
        "visible": True,
        "locked": False,
        "payload": {
            "title": "매수·매도 판단 보조",
            "badge": hero.get("badge"),
            "sell_first": sell_first,
            "no_trade_explainer": no_trade,
            "replay_confidence_badge": decision_assistant.get("replay_confidence_badge"),
            "execution_badge": decision_assistant.get("execution_badge"),
            "counter_thesis": decision_assistant.get("counter_thesis"),
            "driver_chips": why.get("driver_chips") or frontend.get("driver_chips") or [],
            "risk_chips": why.get("risk_chips") or frontend.get("risk_chips") or [],
            "portfolio_impact_map": decision_assistant.get("portfolio_impact_map"),
            "order_draft_preview": plan.get("order_draft_preview") or decision_assistant.get("order_draft_preview"),
        },
    }


def _build_institutional_edge_card(event: dict[str, Any], analysis_object: dict[str, Any]) -> dict[str, Any] | None:
    institutional_edge = analysis_object.get("institutional_edge")
    if not isinstance(institutional_edge, dict) or not institutional_edge:
        return None
    frontend = institutional_edge.get("frontend") if isinstance(institutional_edge.get("frontend"), dict) else {}
    return {
        "card_id": f"card_institutional_edge_{event['event_id']}",
        "card_type": "institutional_edge",
        "priority": 5,
        "visible": True,
        "locked": False,
        "payload": {
            "title": "Institutional Edge Pack",
            "approval_state": institutional_edge.get("approval_state"),
            "grade": institutional_edge.get("grade"),
            "score": institutional_edge.get("institutional_grade_score"),
            "summary": frontend.get("summary"),
            "subscores": institutional_edge.get("subscores") or {},
            "capacity": institutional_edge.get("capacity") or {},
            "blockers": institutional_edge.get("blockers") or [],
            "kill_conditions": institutional_edge.get("kill_conditions") or [],
            "red_team": institutional_edge.get("red_team") or {},
            "moat_vs_retail_ai": institutional_edge.get("moat_vs_retail_ai") or [],
        },
    }


def _build_unlock_offer_card(event: dict[str, Any], product_surface: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(product_surface, dict):
        return None
    front_payload = product_surface.get("front_payload_ko") if isinstance(product_surface.get("front_payload_ko"), dict) else {}
    primary_surface = front_payload.get("primary_surface") if isinstance(front_payload, dict) else None
    if not isinstance(primary_surface, dict):
        return None
    unlock_cards = front_payload.get("unlock_cards") or []
    if not unlock_cards:
        return None
    return {
        "card_id": f"card_unlock_{event['event_id']}",
        "card_type": "unlock_offer",
        "priority": 6,
        "visible": True,
        "locked": False,
        "payload": {
            "title": primary_surface.get("title"),
            "reason": primary_surface.get("reason"),
            "unlock_cards": unlock_cards,
        },
    }


def _build_replay(event: dict[str, Any], analysis: dict[str, Any], analysis_object: dict[str, Any]) -> dict[str, Any]:
    hold_days = max(1, int(analysis.get("hold_days") or 1))
    return {
        "status": "tracking",
        "original_signal": {
            "decision": _decision_code(
                analysis_object.get("direction"),
                analysis_object.get("confidence"),
                None,
            ),
            "strategy": analysis.get("strategy"),
            "hold_days": hold_days,
        },
        "milestones": [
            {"day": "D+1", "status": "pending"},
            {"day": f"D+{hold_days}", "status": "pending"},
        ],
        "expected_path": analysis_object.get("signal_explanation", {}).get("hold_period_reason") or "보유기간 내 성과 집중 여부를 추적합니다.",
        "exit_watch": analysis_object.get("signal_explanation", {}).get("counter_scenario"),
    }


def _build_paywall(product_surface: dict[str, Any]) -> dict[str, Any]:
    front_payload = product_surface.get("front_payload_ko") if isinstance(product_surface, dict) else {}
    frontend_contract = product_surface.get("frontend_contract_ko") if isinstance(product_surface, dict) else {}
    return {
        "schema_version": product_surface.get("schema_version") if isinstance(product_surface, dict) else None,
        "primary_surface": front_payload.get("primary_surface") if isinstance(front_payload, dict) else None,
        "secondary_surfaces": front_payload.get("secondary_surfaces") if isinstance(front_payload, dict) else [],
        "unlock_cards": front_payload.get("unlock_cards") if isinstance(front_payload, dict) else [],
        "summary": front_payload.get("summary") if isinstance(front_payload, dict) else None,
        "frontend_contract_ko": frontend_contract,
    }


def build_engine_event_response(*, payload: AnalyzeRequest, analysis: dict[str, Any]) -> dict[str, Any]:
    ts = _utc_now()
    request_id = _build_request_id(ts, payload)
    metadata = analysis.get("metadata") if isinstance(analysis.get("metadata"), dict) else {}
    request_metadata = payload.request_metadata if isinstance(getattr(payload, "request_metadata", None), dict) else {}
    event_id = _build_event_id(ts, payload)
    event = _build_event_summary(event_id=event_id, ts=ts, payload=payload, metadata=metadata)
    market_snapshot = _build_market_snapshot(payload.market_data)
    analysis_object = _build_analysis_object(analysis, payload.market_data)
    product_surface = metadata.get("product_surface") if isinstance(metadata, dict) else {}
    signal_explanation = metadata.get("signal_explanation") if isinstance(metadata, dict) else {}
    signal_brief = build_signal_brief(
        analysis=analysis,
        analysis_object=analysis_object,
        product_surface=product_surface if isinstance(product_surface, dict) else None,
    )
    replay = _build_replay(event, analysis, analysis_object)

    cards = [
        _build_hero_card(event, analysis_object, product_surface, signal_explanation),
        _build_why_card(event, analysis_object),
        _build_trade_card(event, analysis, product_surface),
    ]
    decision_assistant_card = _build_decision_assistant_card(event, analysis_object)
    if decision_assistant_card:
        cards.append(decision_assistant_card)
    risk_card = _build_risk_card(event, analysis_object)
    if risk_card:
        cards.append(risk_card)
    institutional_edge_card = _build_institutional_edge_card(event, analysis_object)
    if institutional_edge_card:
        cards.append(institutional_edge_card)
    unlock_offer = _build_unlock_offer_card(event, product_surface)
    if unlock_offer:
        cards.append(unlock_offer)
    cards.append(
        {
            "card_id": f"card_replay_{event['event_id']}",
            "card_type": "replay_summary",
            "priority": 7,
            "visible": True,
            "locked": False,
            "payload": replay,
        }
    )
    cards = sorted(cards, key=lambda item: item.get("priority", 999))

    data = {
        "event": event,
        "market_snapshot": market_snapshot,
        "analysis": analysis_object,
        "signal_brief": signal_brief,
        "cards": cards,
        "paywall": _build_paywall(product_surface),
        "replay": replay,
        "request_metadata": request_metadata,
    }
    return {
        "request_id": request_id,
        "timestamp": _iso(ts),
        "status": "ok",
        "schema_version": _SCHEMA_VERSION,
        "signal_brief": signal_brief,
        "request_metadata": request_metadata,
        "data": data,
    }


__all__ = ["build_engine_event_response"]
