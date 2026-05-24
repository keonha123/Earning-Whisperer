from __future__ import annotations

from core.event_payload_builder import build_engine_event_response
from models.request_models import AnalyzeRequest


def _request() -> AnalyzeRequest:
    return AnalyzeRequest.model_validate(
        {
            "ticker": "NVDA",
            "prompt": "Revenue beat, guidance raised, demand remains strong across AI clusters.",
            "section_type": "GUIDANCE",
            "source_type": "EARNINGS_CALL",
            "chunk_sequence": 2,
            "market_data": {
                "ticker": "NVDA",
                "current_price": 950.0,
                "gap_pct": 4.2,
                "surprise_pct": 11.4,
                "volume_ratio": 2.6,
                "iv_rank": 71.0,
                "rsi_14": 63.0,
                "liquidity_score": 0.92,
                "relative_strength_20d": 8.1,
                "atr_pct_14": 0.032,
            },
        }
    )


def _analysis() -> dict:
    return {
        "direction": "BULLISH",
        "magnitude": 0.86,
        "confidence": 0.89,
        "rationale": "Beat and raise with strong demand and margins.",
        "catalyst_type": "GUIDANCE_UP",
        "strategy": "PEAD",
        "hold_days": 4,
        "risk_flags": ["gap_failure"],
        "metadata": {
            "strategy_score": 0.84,
            "company_name": "NVIDIA",
            "sector": "Semiconductors",
            "trade_plan": {
                "entry_style": "buy_pullback_or_breakout",
                "entry_zone": "948-955",
                "stop_loss": 925.0,
                "take_profit_1": 978.0,
                "take_profit_2": 995.0,
                "time_stop_days": 4,
                "sizing_hint": "half_size",
                "execution_notes": ["wait for pullback or breakout confirmation"],
            },
            "signal_explanation": {
                "display_text": "Raised guidance and strong demand support a bullish continuation setup.",
                "summary_ko": "실적 발표 이후 상방 지속 가능성이 높은 Long 후보입니다.",
                "key_factors_ko": ["가이던스 상향", "AI 수요 강화", "마진 개선"],
                "counterfactors_ko": ["초반 갭 메우기 가능성"],
                "transcript_modifiers_ko": ["경영진 톤이 자신감 쪽으로 강화됨"],
                "hold_period_reason_ko": "초기 2~4거래일 동안 후속 수급이 붙을 가능성이 높습니다.",
            },
            "transcript_signals": {
                "topic_deltas": {"guidance": 0.24, "demand": 0.18, "margin": 0.12, "capex": 0.05},
                "confidence_signal": 0.72,
                "evasion_score": 0.09,
                "contradiction_penalty": -0.03,
            },
            "product_surface": {
                "schema_version": "2026-04-19.product-surface.v1",
                "actionability_score": 0.83,
                "recommended_primary_surface": "decision_unlock",
                "recommended_secondary_surfaces": ["power_subscription"],
                "decision_assistant": {
                    "schema_version": "2026-05-03.decision-assistant.v1",
                    "sell_first": {
                        "action": "ADD",
                        "recommended_change_pct": 20.0,
                        "position_intent_ko": "보유 중이면 제한적으로 증액",
                    },
                    "no_trade_explainer": {
                        "blocked": False,
                        "deny_summary_ko": "현재는 신규 진입 차단 사유가 우세하지 않습니다.",
                    },
                    "replay_confidence_badge": {"available": True, "label": "검증 우수", "sample_count": 43},
                    "execution_badge": {"label": "실행 가능", "estimated_all_in_cost_pct": 0.45},
                    "counter_thesis": {"summary_ko": "갭이 실패하면 강세 시나리오가 약해집니다."},
                    "frontend_cards": {
                        "hero": {"badge": "매수 가능", "action": "ADD"},
                        "why": {"driver_chips": [{"label_ko": "실적 서프라이즈"}], "risk_chips": ["gap_failure"]},
                        "plan": {"order_draft_preview": {"broker_execution": "not_called"}},
                    },
                },
                "front_payload_ko": {
                    "primary_surface": {
                        "code": "decision_unlock",
                        "title": "거래 의사결정 Unlock",
                        "reason": "즉시 매매 의사결정에 적합한 신호입니다.",
                    },
                    "secondary_surfaces": [{"code": "power_subscription", "title": "Power 구독"}],
                    "unlock_cards": [{"code": "decision_card", "title": "의사결정 카드"}],
                    "summary": "행동 전환 가능성이 높은 이벤트입니다.",
                },
                "frontend_contract_ko": {
                    "hero": {"title": "Long 후보", "badge": "고확신"},
                    "cta": {"primary": {"action_code": "unlock_decision_card", "label": "판단 보기"}},
                },
            },
            "feature_bundle": {
                "canonical_present": True,
                "coverage": {
                    "company": True,
                    "earnings_event": True,
                    "transcript": True,
                    "guidance": True,
                    "market_overlay": False,
                    "analyst_overlay": False,
                    "source_health": True,
                },
                "coverage_pct": 71.43,
                "source_health_summary": {"total_sources": 2, "healthy_count": 1, "degraded_count": 1, "stale_count": 1},
            },
            "signal_data_hub": {
                "feature_bundle_topic": "feature_bundle:nvda",
                "source_health_topics": ["source_health:benzinga_transcripts"],
                "source_count": 1,
                "stale_source_count": 0,
            },
        },
    }


def test_build_engine_event_response_generates_productized_contract() -> None:
    response = build_engine_event_response(payload=_request(), analysis=_analysis())

    assert response["status"] == "ok"
    assert response["schema_version"] == "2026-04-19.ai-engine-event-v1"
    assert response["request_id"].startswith("req_nvda_")
    assert response["data"]["event"]["event_id"].startswith("evt_nvda_")
    assert response["data"]["event"]["company_name"] == "NVIDIA"
    assert response["data"]["analysis"]["strategy_decision"]["strategy"] == "PEAD"
    assert response["data"]["analysis"]["topic_deltas"]["guidance_delta"] == 0.24
    assert response["signal_brief"]["action"] == "BUY"
    assert response["signal_brief"]["strategy_id"] == "PEAD"
    assert response["signal_brief"]["sell_first_action"] == "ADD"
    assert response["signal_brief"]["replay_confidence_badge"]["label"] == "검증 우수"
    assert response["data"]["analysis"]["feature_bundle"]["canonical_present"] is True
    assert response["data"]["analysis"]["signal_data_hub"]["feature_bundle_topic"] == "feature_bundle:nvda"
    card_types = [card["card_type"] for card in response["data"]["cards"]]
    assert card_types[:3] == ["hero_decision", "why", "trade_plan"]
    assert "decision_assistant" in card_types
    assert "replay_summary" in card_types
    trade_card = next(card for card in response["data"]["cards"] if card["card_type"] == "trade_plan")
    assert trade_card["locked"] is True
    assert trade_card["payload"]["entry_style"] == "buy_pullback_or_breakout"
    assert response["data"]["paywall"]["primary_surface"]["code"] == "decision_unlock"
