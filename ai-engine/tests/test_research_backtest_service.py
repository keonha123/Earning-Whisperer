from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.request_models import MarketData
from models.signal_models import StrategyName
from core.universe_profiles import RiskStyleName, UniverseName
from services.research_backtest_service import BacktestTrade, ResearchBacktestService


def _sample_history() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=90, freq="B")
    close = np.linspace(100.0, 140.0, len(dates))
    open_px = close * 0.995
    high = close * 1.015
    low = close * 0.985
    volume = np.full(len(dates), 1_200_000.0)

    for idx in (25, 40, 55, 70):
        prev = close[idx - 1]
        open_px[idx] = prev * 1.06
        close[idx] = open_px[idx] * 1.04
        high[idx] = close[idx] * 1.02
        low[idx] = open_px[idx] * 0.99
        volume[idx] = 4_500_000.0

    return pd.DataFrame(
        {
            "Open": open_px,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def _vix_history() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=90, freq="B")
    return pd.DataFrame({"Close": np.full(len(dates), 18.0)}, index=dates)


def _history_provider(ticker: str, period: str):
    if ticker == "^VIX":
        return _vix_history()
    return _sample_history()


def _metadata_provider(ticker: str) -> dict[str, object]:
    return {
        "sector": "technology",
        "market_cap": 350_000_000_000.0,
        "floatShares": 1_000_000_000.0,
        "daysToCover": 1.2,
        "revenueGrowth": 0.12,
        "earningsGrowth": 0.18,
        "grossMargins": 0.55,
        "operatingMargins": 0.26,
        "debtToEquity": 42.0,
        "currentRatio": 1.9,
        "totalRevenue": 100_000_000_000.0,
        "freeCashflow": 24_000_000_000.0,
        "has_options": True,
    }


def _trade(ticker: str, signal_at: str, net_return_pct: float) -> BacktestTrade:
    return BacktestTrade(
        ticker=ticker,
        signal_at=signal_at,
        entry_at=signal_at,
        exit_at=signal_at,
        universe_profile="NASDAQ100",
        risk_style="CONSERVATIVE",
        strategy="PEAD",
        regime="normal",
        simulation_mode="price_proxy",
        direction="BULLISH",
        hold_days=1,
        gross_return_pct=net_return_pct,
        net_return_pct=net_return_pct,
        mfe_pct=max(net_return_pct, 0.0),
        mae_pct=min(net_return_pct, 0.0),
        position_scale=1.0,
        benchmark_return_pct=0.0,
        entry_price=100.0,
        exit_price=100.0 * (1.0 + net_return_pct / 100.0),
    )


def test_metrics_sort_by_timestamp_and_count_only_positive_net_returns_as_wins() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)
    trades = [
        BacktestTrade(
            ticker="AAA",
            signal_at="2025-01-03T00:00:00",
            entry_at="2025-01-03T00:00:00",
            exit_at="2025-01-03T00:00:00",
            universe_profile="NASDAQ100",
            risk_style="CONSERVATIVE",
            strategy="PEAD",
            regime="normal",
            simulation_mode="price_proxy",
            direction="BULLISH",
            hold_days=1,
            gross_return_pct=50.0,
            net_return_pct=50.0,
            mfe_pct=55.0,
            mae_pct=-5.0,
            position_scale=1.0,
            benchmark_return_pct=0.0,
            entry_price=100.0,
            exit_price=150.0,
        ),
        BacktestTrade(
            ticker="AAA",
            signal_at="2025-01-02T00:00:00",
            entry_at="2025-01-02T00:00:00",
            exit_at="2025-01-02T00:00:00",
            universe_profile="NASDAQ100",
            risk_style="CONSERVATIVE",
            strategy="PEAD",
            regime="normal",
            simulation_mode="price_proxy",
            direction="BULLISH",
            hold_days=1,
            gross_return_pct=-20.0,
            net_return_pct=-20.0,
            mfe_pct=1.0,
            mae_pct=-22.0,
            position_scale=1.0,
            benchmark_return_pct=0.0,
            entry_price=100.0,
            exit_price=80.0,
        ),
        BacktestTrade(
            ticker="AAA",
            signal_at="2025-01-04T00:00:00",
            entry_at="2025-01-04T00:00:00",
            exit_at="2025-01-04T00:00:00",
            universe_profile="NASDAQ100",
            risk_style="CONSERVATIVE",
            strategy="PEAD",
            regime="normal",
            simulation_mode="price_proxy",
            direction="BULLISH",
            hold_days=1,
            gross_return_pct=0.0,
            net_return_pct=0.0,
            mfe_pct=2.0,
            mae_pct=-1.0,
            position_scale=1.0,
            benchmark_return_pct=0.0,
            entry_price=100.0,
            exit_price=100.0,
        ),
    ]

    metrics = service._compute_metrics(trades, approved_count=3, rejected_count=0, benchmark_return_pct=0.0)

    assert metrics.win_rate_pct == pytest.approx(33.3333, rel=1e-3)
    assert metrics.max_drawdown_pct == pytest.approx(-20.0, abs=0.01)
    assert metrics.wilson_win_rate_lower_pct > 0.0
    assert metrics.bayesian_win_rate_mean_pct == pytest.approx(40.0)
    assert metrics.fractional_kelly_pct >= 0.0


def test_proxy_and_hybrid_modes_return_consistent_artifact_shapes() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    proxy = service.run(
        tickers=["AAA", "BBB"],
        period="9mo",
        min_history=25,
        universe_profile="NASDAQ100",
        risk_style="CONSERVATIVE",
        mode="proxy",
    )
    hybrid = service.run(
        tickers=["AAA", "BBB"],
        period="9mo",
        min_history=25,
        universe_profile="NASDAQ100",
        risk_style="CONSERVATIVE",
        mode="hybrid",
    )

    assert proxy["results"]["proxy"]["simulation_mode"] == "price_proxy"
    assert proxy["effective_result"]["simulation_mode"] == "price_proxy"
    assert "metrics" in proxy["effective_result"]
    assert "breakdowns" in proxy["results"]["proxy"]

    assert hybrid["results"]["proxy"]["simulation_mode"] == "price_proxy"
    assert hybrid["results"]["replay"]["simulation_mode"] == "event_replay"
    assert hybrid["effective_result"]["simulation_mode"] == "price_proxy"
    assert any("fell back to proxy" in note for note in hybrid["notes"])


def test_simulate_proxy_trade_returns_net_trade_with_costs() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)
    frame = service._enrich_history(
        ticker="AAA",
        history=_sample_history(),
        vix_history=_vix_history(),
        metadata=_metadata_provider("AAA"),
    )

    trade = service._simulate_proxy_trade(
        ticker="AAA",
        frame=frame,
        signal_index=25,
        strategy=StrategyName.PEAD,
        hold_days=3,
        direction="BULLISH",
        universe_profile="NASDAQ100",
        risk_style="CONSERVATIVE",
        regime="normal",
        blocked_reasons=[],
        composite_strength=0.72,
    )

    assert trade is not None
    assert trade.net_return_pct <= trade.gross_return_pct


def test_backtest_market_data_normalizes_relative_strength_to_percentage_points() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)
    frame = service._enrich_history(
        ticker="AAA",
        history=_sample_history(),
        vix_history=_vix_history(),
        metadata=_metadata_provider("AAA"),
    )
    row = frame.iloc[30].copy()
    row["relative_strength_20d"] = 0.09

    market_data = service._to_market_data(ticker="AAA", row=row, metadata=_metadata_provider("AAA"))

    assert market_data.relative_strength_20d == pytest.approx(9.0)
    assert service._classify_regime(market_data) == "trend_up"
    assert market_data.ma200 is not None
    assert market_data.stochastic_k is not None
    assert market_data.bb_bandwidth is not None
    assert market_data.revenue_growth_yoy == pytest.approx(12.0)
    assert market_data.earnings_growth_yoy == pytest.approx(18.0)


def test_period_to_lookback_days_uses_exact_date_range_when_provided() -> None:
    lookback = ResearchBacktestService._period_to_lookback_days(
        "9mo",
        start_date="2020-01-01",
        end_date="2025-12-31",
    )

    assert lookback == 2192


def test_run_includes_data_window_fields_for_exact_date_range() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    payload = service.run(
        tickers=["AAA"],
        period="9mo",
        start_date="2020-01-01",
        end_date="2025-12-31",
        min_history=25,
        universe_profile="NASDAQ100",
        risk_style="CONSERVATIVE",
        mode="proxy",
    )

    assert payload["start_date"] == "2020-01-01"
    assert payload["end_date"] == "2025-12-31"
    assert payload["data_window_label"] == "2020-01-01_to_2025-12-31"


def test_acceptance_markdown_includes_total_benchmark_and_state_columns() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)
    markdown = service.render_acceptance_markdown(
        {
            "generated_at": "2026-04-26T00:00:00+00:00",
            "simulation_mode": "proxy",
            "data_window_label": "2017-01-20_to_2026-04-26",
            "selected_prod_candidate": "sp500_conservative",
            "summaries": {
                "sp500_conservative": {
                    "metrics": {
                        "trade_count": 85,
                        "win_rate_pct": 52.9412,
                        "avg_trade_return_pct": 0.3273,
                        "total_return_pct": 27.288,
                        "benchmark_return_pct": 247.2244,
                        "profit_factor": 1.3093,
                        "sharpe_ratio": 1.2648,
                        "max_drawdown_pct": -16.7419,
                    },
                    "promotion_evaluation": {
                        "recommended_state": "hold_candidate",
                        "eligible_for_prod": False,
                    },
                }
            },
        }
    )

    assert "Total Return %" in markdown
    assert "Wilson Lower %" in markdown
    assert "Kelly %" in markdown
    assert "Benchmark %" in markdown
    assert "State" in markdown
    assert "hold_candidate" in markdown


def test_sp500_conservative_gap_approval_enforces_sector_and_composite_rules() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    utility_market_data = MarketData.model_validate(
        {
            "ticker": "NEE",
            "current_price": 81.0,
            "volume_ratio": 2.6,
            "vix": 18.0,
            "gap_pct": 4.1,
            "relative_strength_20d": 8.5,
            "surprise_pct": 12.0,
            "liquidity_score": 0.75,
            "sector_code": "UTILITIES",
            "market_cap_bucket": "large",
        }
    )
    approved, blocked, composite_strength = service._approve_trade(
        profile_name=UniverseName.SP500,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.GAP_AND_GO,
        strategy_score=0.74,
        market_data=utility_market_data,
        raw_score=0.79,
        confidence=0.84,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert composite_strength >= 0.54
    assert "sp500_gap_sector_blocked" in blocked

    communication_market_data = utility_market_data.model_copy(
        update={
            "ticker": "GOOGL",
            "volume_ratio": 1.9,
            "relative_strength_20d": 4.0,
            "surprise_pct": 8.0,
            "sector_code": "COMMUNICATION_SERVICES",
        }
    )
    approved, blocked, composite_strength = service._approve_trade(
        profile_name=UniverseName.SP500,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.GAP_AND_GO,
        strategy_score=0.74,
        market_data=communication_market_data,
        raw_score=0.40,
        confidence=0.84,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert composite_strength < 0.56
    assert "sp500_gap_composite_floor" in blocked


def test_nasdaq100_conservative_approval_blocks_extended_continuation_flags() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    market_data = MarketData.model_validate(
        {
            "ticker": "NVDA",
            "current_price": 980.0,
            "volume_ratio": 2.8,
            "vix": 18.0,
            "gap_pct": 8.6,
            "relative_strength_20d": 11.0,
            "surprise_pct": 18.0,
            "liquidity_score": 0.82,
            "sector_code": "TECHNOLOGY",
            "market_cap_bucket": "mega",
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.PEAD,
        strategy_score=0.81,
        market_data=market_data,
        raw_score=0.78,
        confidence=0.86,
        risk_flags=["overextended_rsi", "stacked_overbought", "nasdaq_conservative_overextended", "nasdaq_gap_extended"],
        regime="trend_up",
    )

    assert approved is False
    assert "nasdaq_conservative_overextended" in blocked
    assert "nasdaq_gap_extended" in blocked


def test_nasdaq100_conservative_negative_gap_news_breakout_does_not_block_on_gap_extension_alone() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    market_data = MarketData.model_validate(
        {
            "ticker": "AMD",
            "current_price": 180.0,
            "volume_ratio": 2.4,
            "vix": 18.0,
            "gap_pct": -8.4,
            "relative_strength_20d": 9.0,
            "surprise_pct": 0.0,
            "liquidity_score": 0.82,
            "sector_code": "TECHNOLOGY",
            "market_cap_bucket": "mega",
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.NEWS_BREAKOUT,
        strategy_score=0.79,
        market_data=market_data,
        raw_score=0.75,
        confidence=0.84,
        risk_flags=[],
        regime="trend_up",
    )

    assert approved is True
    assert "nasdaq_gap_extended" not in blocked


def test_nasdaq100_conservative_blocks_non_core_sector_and_high_vol_news() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    non_core_market_data = MarketData.model_validate(
        {
            "ticker": "LIN",
            "current_price": 440.0,
            "volume_ratio": 2.8,
            "vix": 18.0,
            "gap_pct": 3.2,
            "relative_strength_20d": 8.0,
            "surprise_pct": 12.0,
            "liquidity_score": 0.86,
            "sector_code": "BASIC_MATERIALS",
            "market_cap_bucket": "mega",
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.PEAD,
        strategy_score=0.82,
        market_data=non_core_market_data,
        raw_score=0.78,
        confidence=0.86,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert "nasdaq_conservative_non_core_sector" in blocked

    high_vol_news_market_data = non_core_market_data.model_copy(
        update={
            "ticker": "NVDA",
            "sector_code": "TECHNOLOGY",
            "gap_pct": -4.2,
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.NEWS_BREAKOUT,
        strategy_score=0.82,
        market_data=high_vol_news_market_data,
        raw_score=0.78,
        confidence=0.86,
        risk_flags=[],
        regime="high_vol",
    )

    assert approved is False
    assert "nasdaq_conservative_high_vol_news_breakout" in blocked


def test_nasdaq100_conservative_quality_reversal_scope_requires_mega_core_normal() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    market_data = MarketData.model_validate(
        {
            "ticker": "NVDA",
            "current_price": 980.0,
            "volume_ratio": 2.6,
            "vix": 18.0,
            "gap_pct": -4.4,
            "relative_strength_20d": -4.0,
            "surprise_pct": -8.0,
            "liquidity_score": 0.92,
            "sector_code": "TECHNOLOGY",
            "market_cap_bucket": "mega",
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.REVERSAL_CATALYST,
        strategy_score=0.78,
        market_data=market_data,
        raw_score=-0.78,
        confidence=0.86,
        risk_flags=[],
        regime="normal",
    )

    assert approved is True
    assert "nasdaq_conservative_quality_reversal_scope" not in blocked

    large_cap_market_data = market_data.model_copy(update={"market_cap_bucket": "large"})
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.REVERSAL_CATALYST,
        strategy_score=0.78,
        market_data=large_cap_market_data,
        raw_score=-0.78,
        confidence=0.86,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert "nasdaq_conservative_quality_reversal_scope" in blocked


def test_conservative_approval_blocks_high_execution_cost() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)
    market_data = MarketData.model_validate(
        {
            "ticker": "NVDA",
            "current_price": 980.0,
            "volume_ratio": 2.8,
            "vix": 18.0,
            "gap_pct": 3.2,
            "relative_strength_20d": 8.0,
            "surprise_pct": 12.0,
            "liquidity_score": 0.86,
            "sector_code": "TECHNOLOGY",
            "market_cap_bucket": "mega",
            "bid_ask_spread_bps": 35.0,
        }
    )

    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
        strategy=StrategyName.PEAD,
        strategy_score=0.82,
        market_data=market_data,
        raw_score=0.78,
        confidence=0.86,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert "execution_cost_above_conservative_limit" in blocked


def test_nasdaq100_conservative_risk_governor_skips_after_losses_and_drawdown() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)
    trades = [
        _trade("KEEP_1", "2025-01-02T00:00:00", -2.0),
        _trade("KEEP_2", "2025-01-03T00:00:00", -2.5),
        _trade("SKIP_LOSS_STREAK", "2025-01-06T00:00:00", -8.0),
        _trade("KEEP_3", "2025-02-10T00:00:00", -9.0),
        _trade("SKIP_DRAWDOWN", "2025-02-18T00:00:00", -4.0),
        _trade("KEEP_4", "2025-03-20T00:00:00", 3.0),
    ]

    kept, skipped_count = service._apply_track_risk_governor(
        trades,
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.CONSERVATIVE,
    )

    assert skipped_count == 2
    assert [trade.ticker for trade in kept] == ["KEEP_1", "KEEP_2", "KEEP_3", "KEEP_4"]


def test_nasdaq100_aggressive_approval_blocks_non_reversal_and_weak_reversal_sectors() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    market_data = MarketData.model_validate(
        {
            "ticker": "NVDA",
            "current_price": 980.0,
            "volume_ratio": 2.8,
            "vix": 18.0,
            "gap_pct": 5.6,
            "relative_strength_20d": 9.0,
            "surprise_pct": 18.0,
            "liquidity_score": 0.82,
            "sector_code": "TECHNOLOGY",
            "market_cap_bucket": "mega",
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.AGGRESSIVE,
        strategy=StrategyName.PEAD,
        strategy_score=0.82,
        market_data=market_data,
        raw_score=0.79,
        confidence=0.85,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert "nasdaq_aggressive_strategy_blocked" in blocked

    blocked_sector_market_data = market_data.model_copy(
        update={
            "ticker": "TSLA",
            "sector_code": "CONSUMER_CYCLICAL",
            "gap_pct": 6.0,
            "relative_strength_20d": 2.0,
            "surprise_pct": -6.0,
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.NASDAQ100,
        risk_style=RiskStyleName.AGGRESSIVE,
        strategy=StrategyName.REVERSAL_CATALYST,
        strategy_score=0.78,
        market_data=blocked_sector_market_data,
        raw_score=-0.76,
        confidence=0.82,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert "nasdaq_aggressive_sector_blocked" in blocked


def test_sp500_aggressive_approval_blocks_non_pead_and_weak_pead_sectors() -> None:
    service = ResearchBacktestService(history_provider=_history_provider, metadata_provider=_metadata_provider)

    market_data = MarketData.model_validate(
        {
            "ticker": "MSFT",
            "current_price": 420.0,
            "volume_ratio": 2.4,
            "vix": 18.0,
            "gap_pct": 4.0,
            "relative_strength_20d": 8.0,
            "surprise_pct": 0.0,
            "liquidity_score": 0.84,
            "sector_code": "TECHNOLOGY",
            "market_cap_bucket": "mega",
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.SP500,
        risk_style=RiskStyleName.AGGRESSIVE,
        strategy=StrategyName.GAP_AND_GO,
        strategy_score=0.76,
        market_data=market_data,
        raw_score=0.72,
        confidence=0.82,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert "sp500_aggressive_strategy_blocked" in blocked

    blocked_sector_market_data = market_data.model_copy(
        update={
            "ticker": "LLY",
            "sector_code": "HEALTHCARE",
            "surprise_pct": 16.0,
        }
    )
    approved, blocked, _ = service._approve_trade(
        profile_name=UniverseName.SP500,
        risk_style=RiskStyleName.AGGRESSIVE,
        strategy=StrategyName.PEAD,
        strategy_score=0.80,
        market_data=blocked_sector_market_data,
        raw_score=0.78,
        confidence=0.84,
        risk_flags=[],
        regime="normal",
    )

    assert approved is False
    assert "sp500_aggressive_sector_blocked" in blocked
