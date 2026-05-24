from __future__ import annotations

from core.product_surface import build_product_surface
from core.signal_explainer import build_signal_explanation
from core.trade_plan import build_trade_plan
from core.options_advisor import build_options_advice
from models.request_models import MarketData, SectionType, SourceType
from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


def _market_data(**overrides) -> MarketData:
    payload = {
        'ticker': 'NVDA',
        'current_price': 100.0,
        'gap_pct': 5.4,
        'surprise_pct': 15.0,
        'post_earnings_drift_pct': 4.6,
        'iv_rank': 73.0,
        'current_iv': 0.62,
        'volume_ratio': 2.8,
        'relative_strength_20d': 9.0,
        'vix': 18.0,
        'beta_20d': 1.15,
        'liquidity_score': 0.88,
        'next_earnings_days': 24,
        'rsi_14': 64.0,
        'realized_vol_10d': 0.31,
        'atr_pct_14': 0.03,
    }
    payload.update(overrides)
    return MarketData.model_validate(payload)


def test_product_surface_recommends_decision_unlock_for_high_value_earnings_signal() -> None:
    analysis = GeminiAnalysisResult(
        direction='BULLISH',
        magnitude=0.81,
        confidence=0.87,
        rationale='Beat and raise with strong demand commentary.',
        catalyst_type='GUIDANCE_UP',
        metadata={
            'hold_tuning': {'base_hold_days': 2, 'final_hold_days': 3, 'adjustments': [{'reason': 'follow_through_strong'}]},
            'transcript_signals': {'topic_deltas': {'guidance': 0.22, 'demand': 0.19, 'margin': 0.11, 'capex': 0.04}},
        },
    )
    decision = StrategyDecision(
        strategy=StrategyName.PEAD,
        score=0.84,
        hold_days=3,
        rationale='strong continuation setup',
        risk_flags=[],
        metadata={},
    )

    explanation = build_signal_explanation(
        market_data=_market_data(),
        analysis=analysis,
        strategy_decision=decision,
        section_type=SectionType.GUIDANCE,
        source_type=SourceType.EARNINGS_CALL,
    )
    trade_plan = build_trade_plan(_market_data(), decision, analysis)
    options_advice = build_options_advice(_market_data(), decision, analysis)
    surface = build_product_surface(
        market_data=_market_data(),
        analysis=analysis,
        strategy_decision=decision,
        source_type=SourceType.EARNINGS_CALL,
        signal_explanation=explanation,
        trade_plan=trade_plan,
        options_advice=options_advice,
    )

    assert surface['recommended_primary_surface'] == 'decision_unlock'
    assert surface['front_payload_ko']['primary_surface']['title'] == '건별 의사결정 Unlock'
    assert surface['front_payload_ko']['execution_partner']['eligible'] is True
    assert surface['frontend_contract_ko']['hero']['badge'] == '고확신'
    assert surface['frontend_contract_ko']['cta']['primary']['action_code'] == 'unlock_decision_card'
    codes = [item['code'] for item in surface['front_payload_ko']['unlock_cards']]
    assert 'decision_card' in codes
    assert 'execution_playbook' in codes


def test_product_surface_falls_back_to_free_signal_when_edge_is_weak() -> None:
    analysis = GeminiAnalysisResult(
        direction='NEUTRAL',
        magnitude=0.28,
        confidence=0.41,
        rationale='Mixed remarks and limited follow-through.',
        catalyst_type='MIXED',
        metadata={},
    )
    decision = StrategyDecision(
        strategy=StrategyName.SENTIMENT_ONLY,
        score=0.32,
        hold_days=1,
        rationale='weak edge',
        risk_flags=['weak_setup', 'continuation_gate_failed'],
        metadata={},
    )
    explanation = build_signal_explanation(
        market_data=_market_data(volume_ratio=1.1, liquidity_score=0.42),
        analysis=analysis,
        strategy_decision=decision,
        section_type=SectionType.OTHER,
        source_type=SourceType.NEWS,
    )
    trade_plan = build_trade_plan(_market_data(volume_ratio=1.1, liquidity_score=0.42), decision, analysis)
    surface = build_product_surface(
        market_data=_market_data(volume_ratio=1.1, liquidity_score=0.42),
        analysis=analysis,
        strategy_decision=decision,
        source_type=SourceType.NEWS,
        signal_explanation=explanation,
        trade_plan=trade_plan,
        options_advice=None,
    )

    assert surface['recommended_primary_surface'] == 'free_signal'
    assert surface['front_payload_ko']['execution_partner']['eligible'] is False
    assert surface['frontend_contract_ko']['hero']['badge'] == '참고용'
    assert surface['decision_intensity'] == 'low'
