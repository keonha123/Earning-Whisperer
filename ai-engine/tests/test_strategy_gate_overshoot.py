from __future__ import annotations

from models.request_models import MarketData, SectionType
from models.signal_models import GeminiAnalysisResult, StrategyName
from strategies.orchestrator import choose_strategy


def _market_data(**overrides) -> MarketData:
    payload = {
        'ticker': 'TSLA',
        'current_price': 220.0,
        'prev_close': 200.0,
        'gap_pct': 12.0,
        'surprise_pct': 10.0,
        'post_earnings_drift_pct': 1.2,
        'short_interest_pct_float': 3.2,
        'float_rotation': 0.5,
        'days_to_cover': 1.0,
        'iv_rank': 46.0,
        'implied_move_pct': 6.0,
        'current_iv': 0.62,
        'day1_return_pct': 8.4,
        'volume_ratio': 2.3,
        'relative_strength_20d': 5.4,
        'sector_momentum': 4.8,
        'vix': 18.0,
        'beta_20d': 1.9,
        'liquidity_score': 0.81,
        'next_earnings_days': 21,
        'rsi_14': 73.0,
        'analyst_revision_delta_pct': 2.0,
        'hours_since_news': 5.0,
        'realized_vol_10d': 0.042,
    }
    payload.update(overrides)
    return MarketData.model_validate(payload)


def test_continuation_gate_can_fallback_when_gap_overshoots_and_transcript_is_not_supportive() -> None:
    analysis = GeminiAnalysisResult(
        direction='BULLISH',
        magnitude=0.74,
        confidence=0.76,
        rationale='Headline beat, but management avoided specifics and outlook remained vague.',
        catalyst_type='EARNINGS_BEAT',
        negative_word_ratio=0.24,
        metadata={
            'transcript_signals': {
                'evasion_score': 0.66,
                'contradiction_penalty': -0.04,
                'acoustic_stress': 0.02,
                'topic_deltas': {'guidance': -0.02, 'demand': 0.01, 'margin': 0.0, 'capex': 0.0},
            }
        },
    )
    decision = choose_strategy(_market_data(), gemini_result=analysis, section_type=SectionType.Q_AND_A)

    assert 'gap_overshot_implied_move' in decision.risk_flags
    assert 'overshoot_without_transcript_confirmation' in decision.risk_flags
    assert decision.strategy in {StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST, StrategyName.SENTIMENT_ONLY}
