from __future__ import annotations

from core.signal_explainer import build_signal_explanation
from models.request_models import MarketData, SectionType, SourceType
from models.signal_models import GeminiAnalysisResult
from strategies.orchestrator import choose_strategy


def _market_data(**overrides) -> MarketData:
    payload = {
        'current_price': 100.0,
        'gap_pct': 4.8,
        'surprise_pct': 14.0,
        'post_earnings_drift_pct': 4.2,
        'iv_rank': 74.0,
        'current_iv': 0.58,
        'volume_ratio': 2.6,
        'relative_strength_20d': 7.0,
        'vix': 18.0,
        'beta_20d': 1.15,
        'liquidity_score': 0.82,
        'next_earnings_days': 18,
        'rsi_14': 66.0,
        'realized_vol_10d': 0.29,
        'atr_pct_14': 0.028,
        'hours_since_news': 4.0,
    }
    payload.update(overrides)
    return MarketData.model_validate(payload)


def test_pead_hold_days_can_extend_when_follow_through_quality_is_strong() -> None:
    analysis = GeminiAnalysisResult(
        direction='BULLISH',
        magnitude=0.81,
        confidence=0.86,
        rationale='Strong earnings call with raised guidance.',
        catalyst_type='EARNINGS_BEAT',
        metadata={'transcript_signals': {'evasion_score': 0.18, 'contradiction_penalty': 0.0, 'acoustic_stress': 0.0}},
    )

    decision = choose_strategy(_market_data(), gemini_result=analysis, section_type=SectionType.Q_AND_A)

    assert decision.strategy.value in {'PEAD', 'WHISPER_PLAY', 'GAP_AND_GO', 'NEWS_BREAKOUT'}
    assert decision.hold_days >= decision.metadata['hold_tuning']['base_hold_days']
    assert decision.metadata['hold_tuning']['final_hold_days'] == decision.hold_days
    assert 'mfe_mae_profile' in decision.metadata['hold_tuning']
    assert any(item['reason'] for item in decision.metadata['hold_tuning']['adjustments'])


def test_signal_explanation_includes_key_drivers_and_hold_reason() -> None:
    analysis = GeminiAnalysisResult(
        direction='BULLISH',
        magnitude=0.79,
        confidence=0.84,
        rationale='Positive tone and raised outlook.',
        catalyst_type='EARNINGS_BEAT',
        metadata={
            'event_quality': {'pead': {'total': 0.78}},
            'hold_tuning': {
                'base_hold_days': 2,
                'final_hold_days': 3,
                'adjustments': [
                    {'reason': 'score_and_volume_confirmation_strong', 'before': 2, 'after': 3}
                ],
            },
            'transcript_signals': {'evasion_score': 0.72, 'contradiction_penalty': 0.0, 'acoustic_stress': 0.0, 'topic_deltas': {'guidance': 0.24, 'demand': 0.18, 'margin': 0.0, 'capex': 0.0}},
        },
    )
    decision = choose_strategy(_market_data(), gemini_result=analysis, section_type=SectionType.Q_AND_A)
    explanation = build_signal_explanation(
        market_data=_market_data(),
        analysis=analysis,
        strategy_decision=decision,
        section_type=SectionType.Q_AND_A,
        source_type=SourceType.EARNINGS_CALL,
    )

    assert 'key drivers:' in explanation['display_text']
    assert explanation['key_factors']
    assert explanation['hold_period_reason'] is not None
    assert explanation['frontend_payload_ko']['headline']
    assert explanation['frontend_payload_ko']['hold']['days'] == decision.hold_days
