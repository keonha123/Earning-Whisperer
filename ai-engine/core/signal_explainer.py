from __future__ import annotations

from typing import Any

try:
    from models.request_models import MarketData, SectionType, SourceType
    from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
except ImportError:  # pragma: no cover
    from ..models.request_models import MarketData, SectionType, SourceType
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}%"


def _percentage_points(value: float | None) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return numeric * 100.0 if abs(numeric) <= 1.0 else numeric


def _strategy_label(strategy: StrategyName) -> str:
    labels = {
        StrategyName.PEAD: "PEAD continuation",
        StrategyName.GAP_AND_GO: "gap-and-go continuation",
        StrategyName.GAP_FILL: "gap-fill mean reversion",
        StrategyName.REVERSAL_CATALYST: "reversal catalyst",
        StrategyName.IV_CRUSH_DECAY: "IV-crush decay",
        StrategyName.SHORT_SQUEEZE: "short-squeeze continuation",
        StrategyName.WHISPER_PLAY: "whisper-play breakout",
        StrategyName.NEWS_BREAKOUT: "news breakout",
        StrategyName.MOMENTUM_CARRY: "momentum carry",
        StrategyName.SENTIMENT_ONLY: "sentiment-only",
    }
    return labels.get(strategy, strategy.value.lower())


def _strategy_label_ko(strategy: StrategyName) -> str:
    labels = {
        StrategyName.PEAD: "실적발표 후 드리프트 지속",
        StrategyName.GAP_AND_GO: "갭 상승 지속",
        StrategyName.GAP_FILL: "갭 메우기 역추세",
        StrategyName.REVERSAL_CATALYST: "반전 촉매",
        StrategyName.IV_CRUSH_DECAY: "변동성 축소",
        StrategyName.SHORT_SQUEEZE: "숏스퀴즈 지속",
        StrategyName.WHISPER_PLAY: "위스퍼 상회 돌파",
        StrategyName.NEWS_BREAKOUT: "뉴스 돌파",
        StrategyName.MOMENTUM_CARRY: "모멘텀 캐리",
        StrategyName.SENTIMENT_ONLY: "단기 센티먼트",
    }
    return labels.get(strategy, strategy.value)


def _direction_ko(direction: str) -> str:
    return {"BULLISH": "매수", "BEARISH": "매도", "NEUTRAL": "중립"}.get(str(direction).upper(), "중립")


def _contribution(feature: str, direction: str, magnitude: float, label_ko: str, badge_ko: str) -> dict[str, Any]:
    return {
        "feature": feature,
        "direction": direction,
        "magnitude": round(float(magnitude), 4),
        "label_ko": label_ko,
        "badge_ko": badge_ko,
    }


def _topic_delta_to_korean(topic: str, value: float) -> str | None:
    if value >= 0.16:
        mapping = {
            "guidance": "가이던스 언급이 상향 쪽으로 이동했습니다.",
            "capex": "CAPEX 언급이 확대 방향으로 이동했습니다.",
            "margin": "마진 관련 코멘트가 개선 쪽으로 이동했습니다.",
            "demand": "수요 관련 코멘트가 개선 쪽으로 이동했습니다.",
        }
        return mapping.get(topic)
    if value <= -0.16:
        mapping = {
            "guidance": "가이던스 언급이 하향 쪽으로 이동했습니다.",
            "capex": "CAPEX 언급이 축소 또는 보수화 방향으로 이동했습니다.",
            "margin": "마진 관련 코멘트가 약화 쪽으로 이동했습니다.",
            "demand": "수요 관련 코멘트가 둔화 쪽으로 이동했습니다.",
        }
        return mapping.get(topic)
    return None


def build_signal_explanation(
    *,
    market_data: MarketData,
    analysis: GeminiAnalysisResult,
    strategy_decision: StrategyDecision,
    section_type: SectionType,
    source_type: SourceType,
) -> dict[str, Any]:
    relative_strength_points = _percentage_points(market_data.relative_strength_20d)
    factors: list[str] = []
    factors_ko: list[str] = []
    counterfactors: list[str] = []
    counterfactors_ko: list[str] = []
    transcript_notes: list[str] = []
    transcript_notes_ko: list[str] = []
    tags_ko: list[str] = []

    if abs(market_data.surprise_pct) >= 8:
        factors.append(f"earnings surprise was meaningful at {_fmt_pct(market_data.surprise_pct)}")
        factors_ko.append(f"실적 서프라이즈가 {_fmt_pct(market_data.surprise_pct)}로 컸습니다.")
        tags_ko.append("실적 서프라이즈")
    if abs(market_data.gap_pct) >= 3:
        factors.append(f"price opened with a notable gap of {_fmt_pct(market_data.gap_pct)}")
        factors_ko.append(f"시가 갭이 {_fmt_pct(market_data.gap_pct)}로 크게 형성됐습니다.")
        tags_ko.append("갭 발생")
    if market_data.volume_ratio >= 1.8:
        factors.append(f"volume confirmation was strong at {market_data.volume_ratio:.2f}x normal")
        factors_ko.append(f"거래량이 평소 대비 {market_data.volume_ratio:.2f}배로 강하게 확인됐습니다.")
        tags_ko.append("거래량 강함")
    if abs(market_data.post_earnings_drift_pct) >= 2.5:
        factors.append(f"post-event drift already developed by {_fmt_pct(market_data.post_earnings_drift_pct)}")
        factors_ko.append(f"이벤트 이후 드리프트가 {_fmt_pct(market_data.post_earnings_drift_pct)} 진행됐습니다.")
    if relative_strength_points >= 5:
        factors.append(f"relative strength was supportive at {_fmt_pct(relative_strength_points)} over 20d")
        factors_ko.append(f"20일 상대강도가 {_fmt_pct(relative_strength_points)}로 우호적입니다.")
    if market_data.ma_stack_bullish:
        factors.append("moving-average stack remained bullish across 20/50/200 day filters")
        factors_ko.append("20/50/200일 이동평균 정배열이 유지되고 있습니다.")
    if str(market_data.ichimoku_weekly_cloud_bias or "").lower() == "bullish":
        factors.append("weekly ichimoku cloud stayed supportive")
        factors_ko.append("주봉 일목균형표 구름대가 우호적입니다.")
    if market_data.spy_relative_strength_20d is not None and float(market_data.spy_relative_strength_20d) >= 3.0:
        factors.append(f"the name outperformed SPY by {_fmt_pct(market_data.spy_relative_strength_20d)} over 20d")
        factors_ko.append(f"20일 기준 SPY 대비 {_fmt_pct(market_data.spy_relative_strength_20d)} 초과강세입니다.")
    if market_data.qqq_relative_strength_20d is not None and float(market_data.qqq_relative_strength_20d) >= 3.0:
        factors.append(f"the name outperformed QQQ by {_fmt_pct(market_data.qqq_relative_strength_20d)} over 20d")
        factors_ko.append(f"20일 기준 QQQ 대비 {_fmt_pct(market_data.qqq_relative_strength_20d)} 초과강세입니다.")
    if market_data.revenue_growth_yoy is not None and market_data.earnings_growth_yoy is not None:
        if float(market_data.revenue_growth_yoy) > 0.0 and float(market_data.earnings_growth_yoy) > 0.0:
            factors.append("financial statement growth remained positive on both revenue and earnings")
            factors_ko.append("재무제표 기준 매출과 이익 성장률이 모두 플러스입니다.")
    if market_data.iv_rank >= 65:
        factors.append(f"implied volatility was elevated with IV rank {market_data.iv_rank:.0f}")
        factors_ko.append(f"IV Rank가 {market_data.iv_rank:.0f}로 높습니다.")
    if analysis.confidence >= 0.78:
        factors.append(f"LLM conviction was high at {analysis.confidence:.2f} confidence")
        factors_ko.append(f"모델 신뢰도가 {analysis.confidence:.2f}로 높습니다.")

    event_quality = None
    strategy_key = strategy_decision.strategy.value.lower()
    if analysis.metadata.get("event_quality") and isinstance(analysis.metadata["event_quality"], dict):
        event_quality = analysis.metadata["event_quality"].get(strategy_key)
        if isinstance(event_quality, dict) and event_quality.get("total") is not None:
            factors.append(f"event-quality score for this setup was {event_quality['total']:.2f}")
            factors_ko.append(f"이 전략의 이벤트 품질 점수가 {event_quality['total']:.2f}입니다.")
            tags_ko.append("이벤트 품질 우수")

    transcript_signals = analysis.metadata.get("transcript_signals") if isinstance(analysis.metadata, dict) else None
    if isinstance(transcript_signals, dict):
        if float(transcript_signals.get("evasion_score", 0.0) or 0.0) >= 0.58:
            transcript_notes.append("management sounded evasive in Q&A, so conviction was discounted")
            transcript_notes_ko.append("Q&A에서 답변 회피 성향이 보여 확신도를 낮췄습니다.")
            counterfactors_ko.append("Q&A 회피")
        if float(transcript_signals.get("contradiction_penalty", 0.0) or 0.0) <= -0.14:
            transcript_notes.append("a contradiction risk was detected versus earlier remarks")
            transcript_notes_ko.append("이전 발언과의 모순 가능성이 감지됐습니다.")
            counterfactors_ko.append("발언 모순 리스크")
        if float(transcript_signals.get("acoustic_stress", 0.0) or 0.0) >= 0.08:
            transcript_notes.append("acoustic stress increased during delivery")
            transcript_notes_ko.append("음성 스트레스가 높아져 신호 강도를 일부 할인했습니다.")
            counterfactors_ko.append("음성 스트레스")

        topic_deltas = transcript_signals.get("topic_deltas") or {}
        if isinstance(topic_deltas, dict):
            for topic, value in topic_deltas.items():
                note_ko = _topic_delta_to_korean(topic, float(value or 0.0))
                if note_ko:
                    transcript_notes_ko.append(note_ko)
                    if topic == "guidance" and float(value or 0.0) >= 0.16:
                        tags_ko.append("가이던스 상향")
                    if topic == "demand" and float(value or 0.0) >= 0.16:
                        tags_ko.append("수요 개선")
                    if topic == "margin" and float(value or 0.0) <= -0.16:
                        counterfactors_ko.append("마진 약화")

    for flag in strategy_decision.risk_flags:
        mapping = {
            "high_vix": ("macro volatility regime is elevated", "시장 변동성이 높습니다."),
            "thin_confirmation": ("volume confirmation is thinner than preferred", "거래량 확인이 기대보다 약합니다."),
            "high_beta": ("name is high beta and may overshoot", "변동성이 큰 종목이라 흔들림이 클 수 있습니다."),
            "overextended_rsi": ("RSI is stretched and raises chase risk", "RSI 과열로 추격 매수 리스크가 있습니다."),
            "near_earnings": ("next earnings date is too close", "다음 실적 일정이 가까워 보유 기간을 길게 가져가기 어렵습니다."),
            "stale_catalyst": ("the catalyst is getting stale", "촉매가 오래되어 추세 지속력이 약해질 수 있습니다."),
            "low_event_quality": ("event quality was weaker than ideal for this strategy", "이 전략 기준 이벤트 품질이 충분히 강하지 않습니다."),
            "weak_setup": ("overall tactical edge is weak", "전술적 우위가 약합니다."),
            "management_contradiction_risk": ("management comments conflict with prior statements", "경영진 발언의 일관성이 약합니다."),
            "qa_evasive_answer": ("Q&A answers were evasive", "Q&A 응답이 회피적으로 보입니다."),
            "acoustic_stress_spike": ("delivery stress increased during the call", "콜 진행 중 음성 스트레스가 커졌습니다."),
            "guidance_downshift": ("guidance language shifted downward", "가이던스 톤이 하향 쪽으로 이동했습니다."),
            "margin_pressure_language": ("margin commentary weakened", "마진 관련 코멘트가 약해졌습니다."),
            "demand_softening_language": ("demand commentary softened", "수요 관련 코멘트가 약해졌습니다."),
            "gap_overshot_implied_move": ("price gap already exceeded the implied move", "시가 갭이 옵션 내재 변동 범위를 이미 많이 넘어섰습니다."),
            "overshoot_without_transcript_confirmation": ("gap overshot but transcript follow-through confirmation was weak", "갭은 컸지만 콜 내용이 추세 지속을 충분히 확인해주지 못했습니다."),
            "continuation_gate_failed": ("continuation gate failed so the model shifted to a safer fallback setup", "추세 지속 게이트를 통과하지 못해 더 보수적인 대체 전략으로 전환했습니다."),
            "trend_up_confirmation_gap": ("trend-up continuation lacked confirmation", "상승 추세 구간이지만 추세 지속 확인 신호가 부족했습니다."),
            "sp500_pead_quality_gate_failed": ("SP500 PEAD quality gate rejected the setup", "SP500용 PEAD 품질 게이트를 통과하지 못했습니다."),
            "sp500_gap_sector_blocked": ("SP500 conservative sector filter rejected the continuation setup", "SP500 보수형 섹터 필터가 해당 지속형 진입을 차단했습니다."),
            "sp500_gap_composite_floor": ("SP500 conservative continuation quality stayed below the required floor", "SP500 보수형 지속 전략 품질 점수가 요구 하한선에 미달했습니다."),
            "nasdaq_conservative_overextended": ("Nasdaq100 conservative profile rejected an overextended continuation setup", "Nasdaq100 보수형 프로파일이 과열된 지속형 진입을 차단했습니다."),
            "nasdaq_gap_extended": ("Nasdaq100 conservative profile rejected an oversized gap continuation setup", "Nasdaq100 보수형 프로파일이 과도한 갭 지속형 진입을 차단했습니다."),
            "nasdaq_aggressive_strategy_blocked": ("Nasdaq100 aggressive research track only allows selected reversal setups", "Nasdaq100 공격형 연구 트랙은 선별된 리버설 셋업만 허용합니다."),
            "nasdaq_aggressive_sector_blocked": ("Nasdaq100 aggressive research track rejected the sector reversal cohort", "Nasdaq100 공격형 연구 트랙이 해당 섹터의 리버설 품질을 이유로 차단했습니다."),
            "risk_off_regime_blocked": ("the active profile blocks tactical entries during risk-off regimes", "현재 프로파일은 위험회피 장세에서 전술 진입을 차단합니다."),
            "high_vol_regime_blocked": ("the active profile blocks tactical entries during high-volatility regimes", "현재 프로파일은 고변동성 장세에서 전술 진입을 차단합니다."),
            "low_numeric_specificity": ("management commentary lacked numerical specificity", "수치 기반 구체성이 부족했습니다."),
            "negative_sentiment_velocity": ("sentiment deteriorated across transcript chunks", "콜이 진행될수록 톤이 악화됐습니다."),
            "below_ma200": ("price stayed below the 200-day moving average", "가격이 200일 이동평균 아래에 있습니다."),
            "weekly_cloud_bearish": ("weekly ichimoku cloud stayed bearish", "주봉 일목균형표 구름대가 약세입니다."),
            "stacked_overbought": ("RSI, stochastic, and Bollinger positioning all looked stretched", "RSI, 스토캐스틱, 볼린저밴드가 동시에 과열 구간입니다."),
            "benchmark_underperformance": ("the name underperformed major benchmark proxies", "QQQ/SPY 대비 상대강도가 약합니다."),
            "weak_fundamentals": ("financial statement quality was weak versus the setup", "재무제표 품질이 현재 셋업 대비 약합니다."),
            "zero_dte_flow_opposition": ("same-day options flow leaned against the signal direction", "0DTE 옵션 수급이 신호 방향과 반대입니다."),
            "sp500_aggressive_strategy_blocked": ("SP500 aggressive research track only allows selected PEAD setups", "SP500 공격형 연구 트랙은 선별된 PEAD 셋업만 허용합니다."),
            "sp500_aggressive_sector_blocked": ("SP500 aggressive research track rejected the PEAD sector cohort", "SP500 공격형 연구 트랙이 해당 섹터의 PEAD 품질을 이유로 차단했습니다."),
        }
        if flag in mapping:
            eng, kor = mapping[flag]
            counterfactors.append(eng)
            counterfactors_ko.append(kor)

    hold_tuning = analysis.metadata.get("hold_tuning") if isinstance(analysis.metadata, dict) else None
    hold_reason = None
    hold_reason_ko = None
    hold_badges_ko: list[str] = []
    if isinstance(hold_tuning, dict):
        base_hold = hold_tuning.get("base_hold_days")
        final_hold = hold_tuning.get("final_hold_days", strategy_decision.hold_days)
        adjustment_labels = [item.get("reason") for item in hold_tuning.get("adjustments", []) if item.get("reason")]
        mfe_mae_profile = hold_tuning.get("mfe_mae_profile") if isinstance(hold_tuning.get("mfe_mae_profile"), dict) else {}
        mfe_mae_ratio = mfe_mae_profile.get("expected_mfe_mae_ratio")
        if adjustment_labels:
            hold_reason = f"base hold was {base_hold} day(s), then adjusted because: " + ", ".join(adjustment_labels[:4])
        elif base_hold is not None:
            hold_reason = f"hold period remained at the base {base_hold} day(s)"

        if base_hold is not None:
            delta = int(final_hold) - int(base_hold)
            if delta > 0:
                hold_reason_ko = f"기본 {base_hold}일 보유에서 {delta}일 연장해 총 {final_hold}일로 설정했습니다."
                hold_badges_ko.append("보유기간 연장")
            elif delta < 0:
                hold_reason_ko = f"기본 {base_hold}일 보유에서 {abs(delta)}일 단축해 총 {final_hold}일로 설정했습니다."
                hold_badges_ko.append("보유기간 단축")
            else:
                hold_reason_ko = f"기본 보유기간 {base_hold}일을 유지했습니다."
        if mfe_mae_ratio is not None:
            hold_reason_ko = (hold_reason_ko or "") + f" 예상 MFE/MAE 비율은 {float(mfe_mae_ratio):.2f}입니다."
            hold_badges_ko.append("MFE/MAE 반영")

    summary_parts = [
        f"{analysis.direction} signal using {_strategy_label(strategy_decision.strategy)}",
        f"because {strategy_decision.rationale}",
    ]
    if factors:
        summary_parts.append(f"key drivers: {', '.join(factors[:4])}")
    if counterfactors:
        summary_parts.append(f"main risks: {', '.join(counterfactors[:3])}")
    if transcript_notes and source_type == SourceType.EARNINGS_CALL:
        summary_parts.append(f"transcript modifiers: {', '.join(transcript_notes[:3])}")

    display_text = "; ".join(summary_parts)

    ko_one_liner = f"{_direction_ko(analysis.direction)} 신호입니다. 핵심 전략은 {_strategy_label_ko(strategy_decision.strategy)}입니다."
    if factors_ko:
        ko_summary = ko_one_liner + " " + " ".join(factors_ko[:2])
    else:
        ko_summary = ko_one_liner
    if counterfactors_ko:
        ko_summary += " 다만 " + " / ".join(counterfactors_ko[:2]) + " 리스크가 있습니다."

    frontend_ko = {
        "headline": f"{_direction_ko(analysis.direction)} · {_strategy_label_ko(strategy_decision.strategy)}",
        "summary": ko_summary,
        "summary_short": f"{_direction_ko(analysis.direction)} 신호 · {_strategy_label_ko(strategy_decision.strategy)} 기반",
        "strategy_label": _strategy_label_ko(strategy_decision.strategy),
        "direction": _direction_ko(analysis.direction),
        "score": strategy_decision.score,
        "confidence": round(analysis.confidence, 4),
        "tags": list(dict.fromkeys(tags_ko + hold_badges_ko))[:6],
        "reasons": list(dict.fromkeys(factors_ko))[:5],
        "risks": list(dict.fromkeys(counterfactors_ko))[:5],
        "transcript_notes": list(dict.fromkeys(transcript_notes_ko))[:5],
        "hold": {
            "days": strategy_decision.hold_days,
            "summary": hold_reason_ko,
        },
        "action": {
            "signal": _direction_ko(analysis.direction),
            "why_now": ko_one_liner,
            "reason_summary": " / ".join(list(dict.fromkeys((factors_ko + transcript_notes_ko)[:3]))) if (factors_ko or transcript_notes_ko) else ko_one_liner,
        },
        "badge": "승인 가능" if str(analysis.direction).upper() in {"BULLISH", "BEARISH"} else "관찰",
        "reason_summary": " / ".join(list(dict.fromkeys((factors_ko + transcript_notes_ko)[:3]))) if (factors_ko or transcript_notes_ko) else ko_one_liner,
        "deny_summary": None,
        "driver_chips": list(dict.fromkeys((factors_ko + transcript_notes_ko)[:5])),
        "risk_chips": list(dict.fromkeys(counterfactors_ko[:5])),
    }

    feature_contributions = []
    if factors_ko:
        feature_contributions.append(_contribution("positive_setup", "positive", 0.7, factors_ko[0], "상승 요인"))
    if transcript_notes_ko:
        feature_contributions.append(_contribution("transcript_modifier", "mixed", 0.4, transcript_notes_ko[0], "콜 컨텍스트"))
    if counterfactors_ko:
        feature_contributions.append(_contribution("risk_flag", "negative", 0.6, counterfactors_ko[0], "리스크"))

    return {
        "display_text": display_text,
        "summary": display_text,
        "key_factors": factors,
        "counterfactors": counterfactors,
        "transcript_modifiers": transcript_notes,
        "hold_period_reason": hold_reason,
        "section_type": section_type.value,
        "source_type": source_type.value,
        "summary_ko": ko_summary,
        "key_factors_ko": factors_ko,
        "counterfactors_ko": counterfactors_ko,
        "transcript_modifiers_ko": transcript_notes_ko,
        "hold_period_reason_ko": hold_reason_ko,
        "frontend_payload_ko": frontend_ko,
        "feature_contributions": feature_contributions,
        "top_drivers": list(dict.fromkeys((factors_ko + transcript_notes_ko)[:3])),
        "top_risks": list(dict.fromkeys(counterfactors_ko[:3])),
        "gate_failures": [],
        "blocked_reasons": {
            "gate_rejections": [],
            "control_blocks": [],
            "risk_overrides": [],
        },
        "decision_state": "tradable" if str(analysis.direction).upper() in {"BULLISH", "BEARISH"} else "neutral",
        "control_overrides": [],
        "calibration_segment": None,
        "active_patch_id": None,
        "rollout_bucket": None,
    }
