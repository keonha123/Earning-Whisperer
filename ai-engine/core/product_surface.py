from __future__ import annotations

from typing import Any

try:
    from models.request_models import MarketData, SourceType
    from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
except ImportError:  # pragma: no cover
    from ..models.request_models import MarketData, SourceType
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


_PREMIUM_STRATEGIES = {
    StrategyName.PEAD,
    StrategyName.GAP_AND_GO,
    StrategyName.WHISPER_PLAY,
    StrategyName.SHORT_SQUEEZE,
    StrategyName.NEWS_BREAKOUT,
    StrategyName.IV_CRUSH_DECAY,
    StrategyName.MOMENTUM_CARRY,
}

_MARKETPLACE_PACKS = {
    StrategyName.PEAD: ("post_earnings_drift_pack", "포스트 실적 드리프트 팩"),
    StrategyName.GAP_AND_GO: ("earnings_gap_continuation_pack", "실적 갭 지속 팩"),
    StrategyName.IV_CRUSH_DECAY: ("event_vol_decay_pack", "이벤트 변동성 축소 팩"),
    StrategyName.WHISPER_PLAY: ("whisper_breakout_pack", "위스퍼 돌파 팩"),
    StrategyName.SHORT_SQUEEZE: ("high_short_interest_pack", "숏스퀴즈 이벤트 팩"),
    StrategyName.NEWS_BREAKOUT: ("catalyst_breakout_pack", "촉매 돌파 팩"),
    StrategyName.MOMENTUM_CARRY: ("momentum_carry_pack", "모멘텀 캐리 팩"),
}


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _normalized_score(strategy_decision: StrategyDecision) -> float:
    return _clamp(strategy_decision.score)


def _risk_penalty(risk_flags: list[str]) -> float:
    severe = {
        "weak_setup",
        "continuation_gate_failed",
        "low_event_quality",
        "management_contradiction_risk",
        "qa_evasive_answer",
        "negative_sentiment_velocity",
    }
    mild = {
        "thin_confirmation",
        "high_vix",
        "high_beta",
        "overextended_rsi",
        "stale_catalyst",
        "gap_overshot_implied_move",
    }
    penalty = 0.0
    penalty += 0.12 * sum(1 for flag in risk_flags if flag in severe)
    penalty += 0.05 * sum(1 for flag in risk_flags if flag in mild)
    return min(0.42, penalty)


def _build_unlock_cards_ko(
    *,
    source_type: SourceType,
    strategy_decision: StrategyDecision,
    trade_plan: dict[str, Any] | None,
    options_advice: dict[str, Any] | None,
    signal_explanation: dict[str, Any],
    actionability_score: float,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    cards.append(
        {
            "code": "decision_card",
            "title": "실전 의사결정 카드",
            "priority": 1,
            "recommended": True,
            "preview": f"전략 {strategy_decision.strategy.value} · 보유 {strategy_decision.hold_days}일",
            "why_pay": "요약만으로는 부족하고 실제 진입·손절·보유 판단이 필요하기 때문입니다.",
        }
    )

    hold_summary = signal_explanation.get("hold_period_reason_ko")
    if hold_summary:
        cards.append(
            {
                "code": "hold_tuning",
                "title": "보유기간 튜닝 근거",
                "priority": 2,
                "recommended": strategy_decision.hold_days >= 2,
                "preview": hold_summary,
                "why_pay": "전략별 보유기간 최적화는 수익/손실 비대칭에 직접 연결됩니다.",
            }
        )

    if trade_plan and trade_plan.get("available"):
        cards.append(
            {
                "code": "execution_playbook",
                "title": "진입/청산 플레이북",
                "priority": 3,
                "recommended": actionability_score >= 0.6,
                "preview": f"{trade_plan.get('entry_style', 'standard')} · time stop {trade_plan.get('time_stop_days', strategy_decision.hold_days)}일",
                "why_pay": "시그널보다 더 중요한 것은 실제 체결 구간과 무효화 조건입니다.",
            }
        )

    transcript_notes = signal_explanation.get("transcript_modifiers_ko") or []
    if source_type == SourceType.EARNINGS_CALL and transcript_notes:
        cards.append(
            {
                "code": "historical_twin",
                "title": "유사 콜 패턴 비교",
                "priority": 4,
                "recommended": True,
                "preview": "가이던스·수요·마진 톤 변화 비교",
                "why_pay": "이번 콜이 과거 어떤 성과 패턴과 닮았는지 비교할수록 의사결정 품질이 올라갑니다.",
            }
        )

    if options_advice and options_advice.get("enabled"):
        cards.append(
            {
                "code": "options_playbook",
                "title": "옵션 구조 제안",
                "priority": 5,
                "recommended": True,
                "preview": options_advice.get("preferred_structure") or "defined-risk structure",
                "why_pay": "현물 외에 더 효율적인 레버리지/리스크 구조를 제시할 수 있습니다.",
            }
        )

    if strategy_decision.strategy in _PREMIUM_STRATEGIES:
        cards.append(
            {
                "code": "failure_pattern",
                "title": "실패 패턴 경고",
                "priority": 6,
                "recommended": bool(strategy_decision.risk_flags),
                "preview": "거짓 돌파·과열 추격·Q&A 회피 리스크 점검",
                "why_pay": "좋은 시그널이라도 망가지는 전형적 조건을 미리 알아야 합니다.",
            }
        )

    cards.sort(key=lambda item: int(item.get("priority", 99)))
    return cards[:6]




def _decision_badge_ko(decision_intensity: str, actionability_score: float) -> str:
    if decision_intensity == "high":
        return "고확신"
    if decision_intensity == "medium":
        return "관찰필요"
    return "참고용"


def _primary_cta_ko(primary_surface: str) -> tuple[str, str]:
    mapping = {
        "decision_unlock": ("unlock_decision_card", "전략 카드 열기"),
        "season_pass": ("buy_season_pass", "시즌 패스 보기"),
        "pro_subscription": ("subscribe_pro", "Pro 시작하기"),
        "power_subscription": ("subscribe_power", "Power 보기"),
        "free_signal": ("view_free_summary", "무료 요약 보기"),
    }
    return mapping.get(primary_surface, ("view_signal", "시그널 보기"))


def _build_frontend_contract_ko(
    *,
    primary_surface: str,
    primary_title: str,
    primary_reason: str,
    decision_intensity: str,
    user_value_band: str,
    actionability_score: float,
    unlock_cards: list[dict[str, Any]],
    execution_partner: dict[str, Any],
    marketplace_fit: dict[str, Any],
    research_pack: dict[str, Any],
    secondary_surfaces: list[dict[str, Any]],
) -> dict[str, Any]:
    primary_action_code, primary_action_label = _primary_cta_ko(primary_surface)
    hero_body = (
        f"이 이벤트는 {primary_title}에 가장 적합합니다. "
        f"행동 전환 가능성은 {decision_intensity} 수준이며, 이유는 {primary_reason}"
    )
    secondary_actions = []
    for item in secondary_surfaces[:2]:
        action_code, action_label = _primary_cta_ko(item['code'])
        secondary_actions.append(
            {
                "action_code": action_code,
                "label": action_label,
                "surface_code": item["code"],
                "reason": item["reason"],
            }
        )

    slot_cards = []
    for idx, card in enumerate(unlock_cards[:4], start=1):
        slot_cards.append(
            {
                "slot": f"unlock_{idx}",
                "card_code": card["code"],
                "title": card["title"],
                "preview": card.get("preview"),
                "locked_reason": card.get("why_pay"),
                "recommended": bool(card.get("recommended")),
            }
        )

    return {
        "ui_version": "2026-04-19.front-contract.v1",
        "hero": {
            "badge": _decision_badge_ko(decision_intensity, actionability_score),
            "title": primary_title,
            "body": hero_body,
            "value_band": user_value_band,
            "actionability_score": round(actionability_score, 4),
        },
        "cta": {
            "primary": {
                "action_code": primary_action_code,
                "label": primary_action_label,
                "surface_code": primary_surface,
            },
            "secondary": secondary_actions,
        },
        "unlock_slots": slot_cards,
        "execution_widget": {
            "visible": bool(execution_partner.get("eligible")),
            "title": "브로커 실행 연동",
            "body": execution_partner.get("reason"),
            "cta_label": "브로커에서 실행" if execution_partner.get("eligible") else "실행 연동 조건 미충족",
            "score": execution_partner.get("score"),
        },
        "marketplace_widget": {
            "visible": bool(marketplace_fit.get("eligible")),
            "title": marketplace_fit.get("pack_title"),
            "body": marketplace_fit.get("reason"),
            "cta_label": "전략 팩 보기" if marketplace_fit.get("eligible") else "전략 팩 비노출",
        },
        "research_widget": {
            "visible": bool(research_pack.get("eligible")),
            "title": research_pack.get("pack_name"),
            "body": research_pack.get("reason"),
            "cta_label": "리서치 팩 보기" if research_pack.get("eligible") else "리서치 팩 비노출",
        },
    }


def build_product_surface(
    *,
    market_data: MarketData,
    analysis: GeminiAnalysisResult,
    strategy_decision: StrategyDecision,
    source_type: SourceType,
    signal_explanation: dict[str, Any],
    trade_plan: dict[str, Any] | None = None,
    options_advice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    confidence = _clamp(analysis.confidence)
    strategy_score = _normalized_score(strategy_decision)
    trade_available = 1.0 if trade_plan and trade_plan.get("available") and trade_plan.get("setup_type") != "sentiment_only" else 0.0
    non_neutral_bonus = 1.0 if analysis.direction in {"BULLISH", "BEARISH", "LONG", "SHORT"} else 0.0
    risk_penalty = _risk_penalty(strategy_decision.risk_flags)

    actionability_score = _clamp(
        0.36 * confidence
        + 0.32 * strategy_score
        + 0.18 * trade_available
        + 0.14 * non_neutral_bonus
        - risk_penalty
    )
    if strategy_decision.strategy in {StrategyName.SENTIMENT_ONLY, StrategyName.ERROR_FALLBACK}:
        actionability_score = min(actionability_score, 0.38)

    if actionability_score >= 0.74:
        decision_intensity = "high"
        user_value_band = "high"
    elif actionability_score >= 0.52:
        decision_intensity = "medium"
        user_value_band = "mid"
    else:
        decision_intensity = "low"
        user_value_band = "low"

    if decision_intensity == "high" and source_type == SourceType.EARNINGS_CALL:
        primary_surface = "decision_unlock"
        primary_title = "건별 의사결정 Unlock"
        primary_reason = "실적 이벤트 직후라 지금 이 한 번의 판단 가치가 높습니다."
    elif decision_intensity == "high":
        primary_surface = "pro_subscription"
        primary_title = "Pro 실시간 시그널"
        primary_reason = "반복적으로 비슷한 이벤트를 추적할 가능성이 높습니다."
    elif source_type == SourceType.EARNINGS_CALL and decision_intensity == "medium":
        primary_surface = "season_pass"
        primary_title = "Earnings Season Pass"
        primary_reason = "실적 시즌형 사용 패턴에 맞는 상품으로 연결하기 좋습니다."
    else:
        primary_surface = "free_signal"
        primary_title = "무료 요약 카드"
        primary_reason = "지금은 방향 확인 수준의 무료 카드로 충분합니다."

    secondary_surfaces: list[dict[str, Any]] = []
    if source_type == SourceType.EARNINGS_CALL:
        secondary_surfaces.append(
            {
                "code": "season_pass",
                "title": "Earnings Season Pass",
                "reason": "실적 시즌 동안 다수의 이벤트를 짧게 소비하는 사용자에게 적합합니다.",
            }
        )
    if decision_intensity in {"medium", "high"}:
        secondary_surfaces.append(
            {
                "code": "pro_subscription",
                "title": "Pro 구독",
                "reason": "watchlist 알림과 반복적 시그널 소비에 적합합니다.",
            }
        )
    if options_advice and options_advice.get("enabled"):
        secondary_surfaces.append(
            {
                "code": "power_subscription",
                "title": "Power 구독",
                "reason": "옵션 구조, 고급 플레이북, 더 빠른 알림 같은 고급 기능과 연결됩니다.",
            }
        )

    execution_partner_score = _clamp(
        0.45 * actionability_score
        + 0.15 * (1.0 if (market_data.liquidity_score or 0.0) >= 0.65 else 0.0)
        + 0.15 * (1.0 if (market_data.volume_ratio or 0.0) >= 1.8 else 0.0)
        + 0.15 * (1.0 if trade_available else 0.0)
        + 0.10 * (1.0 if analysis.direction in {"BULLISH", "BEARISH", "LONG", "SHORT"} else 0.0)
    )
    execution_partner = {
        "eligible": execution_partner_score >= 0.66,
        "score": round(execution_partner_score, 4),
        "cta": "브로커 실행 연동 대상" if execution_partner_score >= 0.66 else "실행 연동보다 정보 소비형에 가깝습니다.",
        "reason": (
            "진입 구간·보유기간·리스크 조건이 구체적이라 체결 전환형 수익모델에 적합합니다."
            if execution_partner_score >= 0.66
            else "아직은 참고용 시그널 성격이 더 강합니다."
        ),
    }

    marketplace_code, marketplace_title = _MARKETPLACE_PACKS.get(
        strategy_decision.strategy,
        ("general_event_signal_pack", "이벤트 시그널 팩"),
    )
    marketplace_fit = {
        "eligible": strategy_decision.strategy in _PREMIUM_STRATEGIES and decision_intensity in {"medium", "high"},
        "pack_code": marketplace_code,
        "pack_title": marketplace_title,
        "reason": (
            "반복 판매 가능한 전략형 포맷이라 마켓플레이스/리서치 팩으로 재패키징하기 좋습니다."
            if strategy_decision.strategy in _PREMIUM_STRATEGIES and decision_intensity in {"medium", "high"}
            else "개별 이벤트 해석 비중이 높아 범용 팩화 우선순위는 낮습니다."
        ),
    }

    research_pack = {
        "eligible": source_type == SourceType.EARNINGS_CALL and decision_intensity in {"medium", "high"},
        "pack_name": "Weekly Top Earnings Setups",
        "reason": "실적 이벤트형 시그널이라 주간 리서치 번들로 묶기 쉽습니다." if source_type == SourceType.EARNINGS_CALL else "범용 이벤트라 리서치 팩화 우선순위가 낮습니다.",
    }

    unlock_cards = _build_unlock_cards_ko(
        source_type=source_type,
        strategy_decision=strategy_decision,
        trade_plan=trade_plan,
        options_advice=options_advice,
        signal_explanation=signal_explanation,
        actionability_score=actionability_score,
    )

    front_payload_ko = {
        "primary_surface": {
            "code": primary_surface,
            "title": primary_title,
            "reason": primary_reason,
        },
        "secondary_surfaces": secondary_surfaces[:3],
        "unlock_cards": unlock_cards,
        "execution_partner": execution_partner,
        "marketplace_fit": marketplace_fit,
        "research_pack": research_pack,
        "summary": (
            f"이 시그널은 {primary_title}에 가장 잘 맞고, 행동 전환 가능성은 {decision_intensity} 수준입니다."
        ),
    }

    return {
        "schema_version": "2026-04-19.product-surface.v1",
        "decision_intensity": decision_intensity,
        "user_value_band": user_value_band,
        "actionability_score": round(actionability_score, 4),
        "recommended_primary_surface": primary_surface,
        "recommended_secondary_surfaces": [item["code"] for item in secondary_surfaces[:3]],
        "front_payload_ko": front_payload_ko,
        "frontend_contract_ko": _build_frontend_contract_ko(
            primary_surface=primary_surface,
            primary_title=primary_title,
            primary_reason=primary_reason,
            decision_intensity=decision_intensity,
            user_value_band=user_value_band,
            actionability_score=actionability_score,
            unlock_cards=unlock_cards,
            execution_partner=execution_partner,
            marketplace_fit=marketplace_fit,
            research_pack=research_pack,
            secondary_surfaces=secondary_surfaces[:3],
        ),
    }
