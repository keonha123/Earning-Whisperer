from __future__ import annotations

from core.transcript_signal_enhancer import TranscriptSignalEnhancer
from models.request_models import MarketData, SectionType
from models.signal_models import GeminiAnalysisResult, StrategyName
from strategies.orchestrator import choose_strategy


def _market_data(**overrides) -> MarketData:
    payload = {
        'ticker': 'NVDA',
        'current_price': 980.0,
        'gap_pct': 7.2,
        'surprise_pct': 18.0,
        'post_earnings_drift_pct': 4.6,
        'short_interest_pct_float': 1.4,
        'float_rotation': 0.9,
        'days_to_cover': 1.2,
        'iv_rank': 42.0,
        'current_iv': 0.55,
        'day1_return_pct': 5.4,
        'volume_ratio': 2.8,
        'relative_strength_20d': 9.2,
        'sector_momentum': 7.0,
        'vix': 18.0,
        'beta_20d': 1.3,
        'liquidity_score': 0.84,
        'next_earnings_days': 28,
        'rsi_14': 67.0,
        'analyst_revision_delta_pct': 4.0,
        'hours_since_news': 3.0,
        'realized_vol_10d': 0.038,
        'breakout_20d_pct': 0.04,
        'high_52w': 985.0,
        'ma20': 944.0,
        'ma50': 902.0,
        'ma200': 860.0,
        'ma_stack_bullish': True,
        'volume_zscore_20d': 2.1,
        'bb_bandwidth': 0.12,
        'stochastic_k': 71.0,
        'stochastic_d': 66.0,
        'ichimoku_weekly_cloud_bias': 'bullish',
        'ichimoku_weekly_cloud_score': 1.0,
        'spy_relative_strength_20d': 4.2,
        'qqq_relative_strength_20d': 3.8,
        'beta_spy_60d': 1.1,
        'beta_qqq_60d': 1.2,
        'zero_dte_available': False,
        'zero_dte_put_call_volume_ratio': 1.0,
        'zero_dte_gamma_pressure': 0.0,
        'revenue_growth_yoy': 14.0,
        'earnings_growth_yoy': 18.0,
        'gross_margin': 54.0,
        'operating_margin': 28.0,
        'fcf_margin': 22.0,
        'debt_to_equity': 45.0,
        'current_ratio': 1.8,
    }
    payload.update(overrides)
    return MarketData.model_validate(payload)


def test_strategy_prefers_event_driven_continuation_when_quality_is_high() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.78,
        confidence=0.81,
        rationale='Strong beat, guidance up, and continued AI demand.',
        catalyst_type='EARNINGS_BEAT',
    )
    decision = choose_strategy(_market_data(), gemini_result=analysis, section_type=SectionType.PREPARED_REMARKS)

    assert decision.strategy in {
        StrategyName.WHISPER_PLAY,
        StrategyName.GAP_AND_GO,
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
    }
    assert decision.metadata['event_quality']['gap_and_go']['total'] >= 0.56
    assert decision.hold_days >= 1


def test_strategy_downgrades_when_event_quality_is_weak() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.51,
        confidence=0.66,
        rationale='Management framed the quarter as stable but offered limited new detail.',
        catalyst_type='MACRO_COMMENTARY',
    )
    decision = choose_strategy(
        _market_data(
            gap_pct=9.5,
            surprise_pct=1.5,
            volume_ratio=1.1,
            hours_since_news=96.0,
            rsi_14=79.0,
            realized_vol_10d=0.11,
            analyst_revision_delta_pct=0.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
    )

    assert 'low_event_quality' in decision.risk_flags or decision.strategy != StrategyName.GAP_AND_GO
    assert 'overextended_rsi' in decision.risk_flags
    assert 'stale_catalyst' in decision.risk_flags


def test_strategy_normalizes_decimal_relative_strength_and_applies_profile_hold_floor() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.76,
        confidence=0.83,
        rationale='Beat and raised outlook with sustained AI demand.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            relative_strength_20d=0.09,
            sector_momentum=0.07,
            breakout_20d_pct=0.05,
            volume_ratio=2.9,
            hours_since_news=4.0,
            gap_pct=4.4,
            post_earnings_drift_pct=4.1,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert decision.metadata['strategy_profile']['name'] == 'NASDAQ100'
    assert decision.metadata['strategy_profile']['risk_style'] == 'CONSERVATIVE'
    assert decision.metadata['strategy_profile']['regime'] == 'trend_up'
    assert decision.hold_days >= 4


def test_sp500_conservative_pead_requires_higher_quality_or_falls_back() -> None:
    analysis = GeminiAnalysisResult(
        ticker='MSFT',
        direction='BULLISH',
        magnitude=0.73,
        confidence=0.80,
        rationale='Good quarter, but follow-through conditions are mixed.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='MSFT',
            gap_pct=1.4,
            surprise_pct=11.0,
            post_earnings_drift_pct=4.8,
            volume_ratio=2.0,
            relative_strength_20d=6.0,
            hours_since_news=24.0,
            breakout_20d_pct=0.012,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='SP500',
    )

    assert 'sp500_pead_quality_gate_failed' in decision.risk_flags
    assert decision.strategy != StrategyName.PEAD


def test_sp500_conservative_gap_blocks_utility_continuation() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NEE',
        direction='BULLISH',
        magnitude=0.76,
        confidence=0.82,
        rationale='Post-earnings continuation is positive, but sector quality is not suitable for the conservative SP500 gap track.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='NEE',
            sector_code='UTILITIES',
            gap_pct=4.1,
            surprise_pct=12.0,
            volume_ratio=2.6,
            relative_strength_20d=8.5,
            breakout_20d_pct=0.032,
            hours_since_news=4.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='SP500',
    )

    assert 'sp500_gap_sector_blocked' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_nasdaq100_conservative_blocks_extended_continuation_setup() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.82,
        confidence=0.86,
        rationale='Strong event continuation, but the opening extension is already too stretched for the conservative Nasdaq track.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='NVDA',
            gap_pct=8.6,
            rsi_14=78.0,
            stochastic_k=90.0,
            bb_position=0.95,
            volume_ratio=3.0,
            breakout_20d_pct=0.055,
            relative_strength_20d=11.0,
            hours_since_news=2.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert 'nasdaq_conservative_overextended' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_nasdaq100_conservative_keeps_large_negative_gap_news_breakout_when_not_overheated() -> None:
    analysis = GeminiAnalysisResult(
        ticker='AMD',
        direction='BULLISH',
        magnitude=0.79,
        confidence=0.84,
        rationale='High-conviction news breakout with strong follow-through but without an overheated tape.',
        catalyst_type='PRODUCT_NEWS',
    )

    decision = choose_strategy(
        _market_data(
            ticker='AMD',
            gap_pct=-8.4,
            rsi_14=66.0,
            stochastic_k=68.0,
            bb_position=0.74,
            volume_ratio=2.7,
            breakout_20d_pct=0.05,
            relative_strength_20d=9.0,
            surprise_pct=0.0,
            catalyst_type='PRODUCT_NEWS',
            hours_since_news=2.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert 'nasdaq_gap_extended' not in decision.risk_flags
    assert decision.strategy != StrategyName.SENTIMENT_ONLY


def test_nasdaq100_conservative_blocks_non_core_sector_continuation() -> None:
    analysis = GeminiAnalysisResult(
        ticker='LIN',
        direction='BULLISH',
        magnitude=0.79,
        confidence=0.84,
        rationale='Strong continuation setup but outside the Nasdaq conservative core sector sleeve.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='LIN',
            sector_code='BASIC_MATERIALS',
            market_cap_bucket='mega',
            gap_pct=3.6,
            volume_ratio=2.8,
            breakout_20d_pct=0.05,
            relative_strength_20d=9.0,
            surprise_pct=14.0,
            hours_since_news=3.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert 'nasdaq_conservative_non_core_sector' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_nasdaq100_conservative_blocks_high_vol_news_breakout() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.79,
        confidence=0.84,
        rationale='Strong news breakout but volatility regime is too unstable for conservative Nasdaq continuation.',
        catalyst_type='PRODUCT_NEWS',
    )

    decision = choose_strategy(
        _market_data(
            ticker='NVDA',
            sector_code='TECHNOLOGY',
            market_cap_bucket='mega',
            gap_pct=-4.6,
            vix=27.0,
            volume_ratio=2.9,
            breakout_20d_pct=0.05,
            relative_strength_20d=9.0,
            surprise_pct=0.0,
            hours_since_news=2.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert 'nasdaq_conservative_high_vol_news_breakout' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_conservative_profile_blocks_high_execution_cost() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.80,
        confidence=0.85,
        rationale='Strong event continuation, but current spread is too expensive for conservative execution.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='NVDA',
            bid_ask_spread_bps=35.0,
            gap_pct=3.4,
            volume_ratio=2.9,
            breakout_20d_pct=0.05,
            relative_strength_20d=9.0,
            surprise_pct=14.0,
            hours_since_news=2.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert 'execution_cost_above_conservative_limit' in decision.risk_flags
    assert decision.metadata['execution_cost_model']['estimated_all_in_cost_pct'] > 0.55
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_nasdaq100_aggressive_rotates_non_reversal_setups_into_reversal_sleeve() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.78,
        confidence=0.82,
        rationale='Strong continuation conditions, but the aggressive Nasdaq research track is now limited to selected reversal participation.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='NVDA',
            sector_code='COMMUNICATION_SERVICES',
            gap_pct=2.0,
            day1_return_pct=-4.0,
            post_earnings_drift_pct=-4.0,
            volume_ratio=2.2,
            breakout_20d_pct=0.01,
            relative_strength_20d=0.0,
            sector_momentum=-2.0,
            bb_position=0.7,
            stochastic_k=20.0,
            surprise_pct=18.0,
            hours_since_news=6.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
        risk_style='AGGRESSIVE',
    )

    assert 'nasdaq_aggressive_strategy_blocked' in decision.risk_flags
    assert decision.strategy == StrategyName.REVERSAL_CATALYST


def test_nasdaq100_aggressive_keeps_non_whitelisted_rotation_out_of_reversal_sleeve() -> None:
    analysis = GeminiAnalysisResult(
        ticker='NVDA',
        direction='BULLISH',
        magnitude=0.78,
        confidence=0.82,
        rationale='The setup does not belong to an aggressive Nasdaq reversal-rotation sector.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='NVDA',
            sector_code='TECHNOLOGY',
            gap_pct=2.0,
            day1_return_pct=-4.0,
            post_earnings_drift_pct=-4.0,
            volume_ratio=2.2,
            breakout_20d_pct=0.01,
            relative_strength_20d=0.0,
            sector_momentum=-2.0,
            bb_position=0.7,
            stochastic_k=20.0,
            surprise_pct=18.0,
            hours_since_news=6.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
        risk_style='AGGRESSIVE',
    )

    assert 'nasdaq_aggressive_strategy_blocked' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_nasdaq100_aggressive_blocks_reversal_in_weak_sector_bucket() -> None:
    analysis = GeminiAnalysisResult(
        ticker='TSLA',
        direction='BEARISH',
        magnitude=0.79,
        confidence=0.82,
        rationale='Sharp rejection favors a reversal setup, but the sector cohort is still excluded for the aggressive Nasdaq research track.',
        catalyst_type='GUIDANCE_HOLD',
    )

    decision = choose_strategy(
        _market_data(
            ticker='TSLA',
            sector_code='CONSUMER_CYCLICAL',
            current_price=170.0,
            gap_pct=6.2,
            day1_return_pct=-5.2,
            post_earnings_drift_pct=-3.4,
            volume_ratio=2.7,
            relative_strength_20d=2.0,
            sector_momentum=-1.5,
            ma20=182.0,
            ma50=190.0,
            ma200=210.0,
            ma_stack_bullish=False,
            ichimoku_weekly_cloud_bias='bearish',
            ichimoku_weekly_cloud_score=-1.0,
            breakout_20d_pct=-0.02,
            surprise_pct=-6.0,
            hours_since_news=5.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
        risk_style='AGGRESSIVE',
    )

    assert 'nasdaq_aggressive_sector_blocked' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_conservative_profile_blocks_tactical_entries_in_risk_off_regime() -> None:
    analysis = GeminiAnalysisResult(
        ticker='AAPL',
        direction='BULLISH',
        magnitude=0.71,
        confidence=0.82,
        rationale='Positive quarter, but the tape is weak.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='AAPL',
            relative_strength_20d=-7.0,
            gap_pct=4.0,
            surprise_pct=15.0,
            post_earnings_drift_pct=4.0,
            volume_ratio=2.7,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert 'risk_off_regime_blocked' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_sp500_aggressive_blocks_non_pead_setups() -> None:
    analysis = GeminiAnalysisResult(
        ticker='MSFT',
        direction='BULLISH',
        magnitude=0.74,
        confidence=0.81,
        rationale='Good short-term continuation setup, but the SP500 aggressive research track now accepts only selected PEAD participation.',
        catalyst_type='PRODUCT_NEWS',
    )

    decision = choose_strategy(
        _market_data(
            ticker='MSFT',
            sector_code='TECHNOLOGY',
            gap_pct=4.2,
            surprise_pct=0.0,
            post_earnings_drift_pct=0.8,
            volume_ratio=2.8,
            relative_strength_20d=8.0,
            breakout_20d_pct=0.046,
            hours_since_news=2.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='SP500',
        risk_style='AGGRESSIVE',
    )

    assert 'sp500_aggressive_strategy_blocked' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_sp500_aggressive_blocks_pead_in_weak_sector_bucket() -> None:
    analysis = GeminiAnalysisResult(
        ticker='LLY',
        direction='BULLISH',
        magnitude=0.80,
        confidence=0.84,
        rationale='Strong earnings continuation setup, but the healthcare PEAD cohort is excluded from the aggressive SP500 research track.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='LLY',
            sector_code='HEALTHCARE',
            gap_pct=3.6,
            surprise_pct=16.0,
            post_earnings_drift_pct=4.5,
            volume_ratio=2.7,
            relative_strength_20d=6.0,
            breakout_20d_pct=0.032,
            hours_since_news=4.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='SP500',
        risk_style='AGGRESSIVE',
    )

    assert 'sp500_aggressive_sector_blocked' in decision.risk_flags
    assert decision.strategy == StrategyName.SENTIMENT_ONLY


def test_strategy_reacts_to_higher_timeframe_and_same_day_options_conflicts() -> None:
    analysis = GeminiAnalysisResult(
        ticker='AMD',
        direction='BULLISH',
        magnitude=0.74,
        confidence=0.80,
        rationale='Short-term event setup is positive, but broader structure is mixed.',
        catalyst_type='EARNINGS_BEAT',
    )

    decision = choose_strategy(
        _market_data(
            ticker='AMD',
            current_price=104.0,
            ma20=108.0,
            ma50=106.0,
            ma200=110.0,
            ma_stack_bullish=False,
            ichimoku_weekly_cloud_bias='bearish',
            ichimoku_weekly_cloud_score=-1.0,
            spy_relative_strength_20d=-6.5,
            qqq_relative_strength_20d=-7.0,
            zero_dte_available=True,
            zero_dte_gamma_pressure=-0.35,
            zero_dte_put_call_volume_ratio=1.45,
            revenue_growth_yoy=-4.0,
            earnings_growth_yoy=-9.0,
            operating_margin=6.0,
            debt_to_equity=210.0,
        ),
        gemini_result=analysis,
        section_type=SectionType.PREPARED_REMARKS,
        universe_profile='NASDAQ100',
    )

    assert 'below_ma200' in decision.risk_flags
    assert 'weekly_cloud_bearish' in decision.risk_flags
    assert 'benchmark_underperformance' in decision.risk_flags
    assert 'zero_dte_flow_opposition' in decision.risk_flags
    assert 'weak_fundamentals' in decision.risk_flags
    assert decision.strategy not in {
        StrategyName.GAP_AND_GO,
        StrategyName.WHISPER_PLAY,
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
        StrategyName.SHORT_SQUEEZE,
    }


def test_transcript_enhancer_penalizes_evasive_qa_and_contradictions() -> None:
    enhancer = TranscriptSignalEnhancer()
    first = GeminiAnalysisResult(
        ticker='AAPL',
        direction='BULLISH',
        magnitude=0.72,
        confidence=0.82,
        rationale='We expect iPhone demand to accelerate meaningfully in the second half with better channel inventory.',
        catalyst_type='GUIDANCE_UP',
    )
    snap1 = enhancer.evaluate(
        ticker='AAPL',
        text_chunk='Q: How is demand trending? A: We expect iPhone demand to accelerate meaningfully in the second half with better channel inventory and improved mix.',
        section_type=SectionType.Q_AND_A,
        analysis=first,
    )
    first = enhancer.apply(first, snap1)

    second = GeminiAnalysisResult(
        ticker='AAPL',
        direction='BEARISH',
        magnitude=0.66,
        confidence=0.79,
        rationale='We expect iPhone demand to remain soft in the second half with worse channel inventory and weaker mix.',
        catalyst_type='GUIDANCE_HOLD',
    )
    snap2 = enhancer.evaluate(
        ticker='AAPL',
        text_chunk='Q: What changed on demand? A: It is too early to comment, as we said before, we expect iPhone demand to remain soft in the second half with worse channel inventory and weaker mix.',
        section_type=SectionType.Q_AND_A,
        analysis=second,
    )
    adjusted = enhancer.apply(second, snap2)

    assert 'qa_evasive_answer' in adjusted.risk_flags
    assert 'management_contradiction_risk' in adjusted.risk_flags
    assert adjusted.confidence < 0.79
    assert adjusted.metadata['transcript_signals']['evasion_score'] > 0.0
