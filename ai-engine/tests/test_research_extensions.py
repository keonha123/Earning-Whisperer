from __future__ import annotations

from ..core.backtester import SignalRecord, recommend_operating_mode, run_backtest
from ..core.five_gate_filter import FiveGateFilter
from ..core.execution_style import recommend_execution_style
from ..core.llm_consistency import aggregate_consensus, should_run_consensus
from ..core.token_budgeter import estimate_tokens, plan_prompt_budget
from ..models.request_models import MarketData, SectionType
from ..models.signal_models import GeminiAnalysisResult, MarketRegime, StrategyName


def test_estimate_tokens_uses_conservative_heuristic():
    assert estimate_tokens("abcdefgh") == 2


def test_plan_prompt_budget_uses_fast_model_for_small_prompts():
    plan = plan_prompt_budget("short prompt")
    assert plan.prompt_size == "small"
    assert plan.needs_compaction is False


def test_should_run_consensus_for_low_confidence_result():
    result = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.51,
        confidence=0.60,
        rationale="Weak first pass",
        catalyst_type="EARNINGS_BEAT",
        euphemism_count=0,
    )
    assert should_run_consensus(result, prompt_tokens=400) is True


def test_aggregate_consensus_prefers_weighted_majority():
    results = [
        GeminiAnalysisResult(
            direction="BULLISH",
            magnitude=0.80,
            confidence=0.91,
            rationale="Beat and raised guidance",
            catalyst_type="EARNINGS_BEAT",
            euphemism_count=0,
            negative_word_ratio=0.08,
            cot_reasoning="sample-1",
        ),
        GeminiAnalysisResult(
            direction="BULLISH",
            magnitude=0.76,
            confidence=0.88,
            rationale="Strong demand commentary",
            catalyst_type="EARNINGS_BEAT",
            euphemism_count=1,
            negative_word_ratio=0.05,
            cot_reasoning="sample-2",
        ),
        GeminiAnalysisResult(
            direction="BEARISH",
            magnitude=0.45,
            confidence=0.62,
            rationale="Margin caution",
            catalyst_type="GUIDANCE_HOLD",
            euphemism_count=2,
            negative_word_ratio=0.31,
            cot_reasoning="sample-3",
        ),
    ]

    aggregate = aggregate_consensus(results)

    assert aggregate.direction == "BULLISH"
    assert aggregate.catalyst_type == "EARNINGS_BEAT"
    assert aggregate.consensus_score is not None and aggregate.consensus_score > 0
    assert aggregate.disagreement_score is not None


def test_execution_style_prefers_intraday_for_liquid_gap_and_go():
    market_data = MarketData(
        volume_ratio=3.4,
        gap_pct=4.1,
        bid_ask_spread_bps=7.5,
        liquidity_score=0.95,
    )

    recommendation = recommend_execution_style(
        strategy=StrategyName.GAP_AND_GO,
        composite_score=0.78,
        confidence=0.92,
        trade_approved=True,
        market_data=market_data,
        section_type=SectionType.PREPARED_REMARKS,
    )

    assert recommendation.style == "INTRADAY_EVENT"
    assert recommendation.max_trades_per_session == 2


def test_execution_style_avoids_trade_for_weak_signal():
    recommendation = recommend_execution_style(
        strategy=StrategyName.SENTIMENT_ONLY,
        composite_score=0.30,
        confidence=0.94,
        trade_approved=False,
        market_data=None,
        section_type=SectionType.OTHER,
    )

    assert recommendation.style == "NO_TRADE"
    assert recommendation.max_trades_per_session == 0


def test_backtest_recommends_intraday_when_frequency_and_win_rate_are_high():
    records = [
        SignalRecord(
            ticker="NVDA",
            timestamp=1741827000,
            composite_score=0.82,
            raw_score=0.76,
            trade_approved=True,
            strategy="GAP_AND_GO",
            actual_return=1.6,
        ),
        SignalRecord(
            ticker="AMD",
            timestamp=1741827600,
            composite_score=0.74,
            raw_score=0.69,
            trade_approved=True,
            strategy="NEWS_BREAKOUT",
            actual_return=1.1,
        ),
        SignalRecord(
            ticker="META",
            timestamp=1741828200,
            composite_score=0.79,
            raw_score=0.72,
            trade_approved=True,
            strategy="GAP_AND_GO",
            actual_return=0.9,
        ),
        SignalRecord(
            ticker="AMZN",
            timestamp=1741828800,
            composite_score=0.70,
            raw_score=0.63,
            trade_approved=True,
            strategy="WHISPER_PLAY",
            actual_return=0.7,
        ),
        SignalRecord(
            ticker="NFLX",
            timestamp=1741829400,
            composite_score=0.73,
            raw_score=0.66,
            trade_approved=True,
            strategy="GAP_AND_GO",
            actual_return=1.3,
        ),
        SignalRecord(
            ticker="TSLA",
            timestamp=1741830000,
            composite_score=0.77,
            raw_score=0.71,
            trade_approved=True,
            strategy="SECTOR_CONTAGION",
            actual_return=0.5,
        ),
    ]

    result = run_backtest(records)
    mode = recommend_operating_mode(result)

    assert result.meets_target_win_rate is True
    assert mode["mode"] == "INTRADAY_EVENT"


def test_gate4_rejects_wide_spread_even_when_volume_is_high():
    gate_filter = FiveGateFilter()
    result = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.8,
        confidence=0.9,
        rationale="Event strength",
        catalyst_type="EARNINGS_BEAT",
        euphemism_count=0,
    )
    market_data = MarketData(
        volume_ratio=4.0,
        bid_ask_spread_bps=48.0,
        liquidity_score=0.91,
        vix=16.0,
    )

    filtered = gate_filter.apply(
        composite_score=0.72,
        raw_score=0.68,
        confidence=0.9,
        euphemism_count=0,
        sue_score=2.0,
        momentum_score=0.4,
        market_data=market_data,
        gemini_result=result,
        regime=MarketRegime.NORMAL,
        adj_composite=0.72,
    )

    assert filtered.trade_approved is False
    assert any(gate.value == "g4" for gate in filtered.failed_gates)


def test_gate4_rejects_poor_liquidity_score():
    gate_filter = FiveGateFilter()
    result = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.8,
        confidence=0.9,
        rationale="Event strength",
        catalyst_type="EARNINGS_BEAT",
        euphemism_count=0,
    )
    market_data = MarketData(
        volume_ratio=4.0,
        bid_ask_spread_bps=10.0,
        liquidity_score=0.10,
        vix=16.0,
    )

    filtered = gate_filter.apply(
        composite_score=0.72,
        raw_score=0.68,
        confidence=0.9,
        euphemism_count=0,
        sue_score=2.0,
        momentum_score=0.4,
        market_data=market_data,
        gemini_result=result,
        regime=MarketRegime.NORMAL,
        adj_composite=0.72,
    )

    assert filtered.trade_approved is False
    assert any(gate.value == "g4" for gate in filtered.failed_gates)
