from __future__ import annotations

from core.options_advisor import build_options_advice
from core.trade_plan import build_trade_plan
from models.request_models import MarketData
from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


def _market_data(**overrides) -> MarketData:
    payload = {
        'current_price': 100.0,
        'gap_pct': 5.0,
        'surprise_pct': 12.0,
        'post_earnings_drift_pct': 4.0,
        'iv_rank': 72.0,
        'current_iv': 0.62,
        'volume_ratio': 2.4,
        'relative_strength_20d': 8.0,
        'vix': 19.0,
        'beta_20d': 1.2,
        'liquidity_score': 0.82,
        'next_earnings_days': 20,
        'rsi_14': 64.0,
        'realized_vol_10d': 0.31,
        'atr_pct_14': 0.03,
    }
    payload.update(overrides)
    return MarketData.model_validate(payload)


def test_continuation_trade_plan_produces_order_levels() -> None:
    analysis = GeminiAnalysisResult(
        direction='BULLISH',
        magnitude=0.74,
        confidence=0.8,
        rationale='Beat and raise with strong follow-through.',
        catalyst_type='EARNINGS_BEAT',
    )
    decision = StrategyDecision(
        strategy=StrategyName.PEAD,
        score=0.77,
        hold_days=3,
        rationale='continuation setup',
        risk_flags=[],
        metadata={},
    )

    plan = build_trade_plan(_market_data(), decision, analysis)

    assert plan['available'] is True
    assert plan['setup_type'] == 'continuation'
    assert plan['entry_zone'][0] < plan['entry_zone'][1]
    assert plan['stop_loss'] < plan['reference_price']
    assert plan['take_profit_2'] > plan['take_profit_1']


def test_iv_crush_prefers_defined_risk_premium_selling() -> None:
    analysis = GeminiAnalysisResult(
        direction='BEARISH',
        magnitude=0.63,
        confidence=0.76,
        rationale='Move looks exhausted after the event and vol remains elevated.',
        catalyst_type='POST_EVENT',
    )
    decision = StrategyDecision(
        strategy=StrategyName.IV_CRUSH_DECAY,
        score=0.71,
        hold_days=2,
        rationale='volatility decay setup',
        risk_flags=[],
        metadata={},
    )

    advice = build_options_advice(_market_data(), decision, analysis)

    assert advice is not None
    assert advice['enabled'] is True
    assert advice['theme'] == 'event_volatility_decay'
    assert advice['preferred_structure'] == 'bear_call_spread'
    assert advice['iv_rv_ratio'] == 2.0
