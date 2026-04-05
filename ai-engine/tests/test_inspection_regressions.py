from __future__ import annotations

import math

import numpy as np

from api.analyze_router import _compute_momentum_score
from core.backtester import _calc_mdd, _calc_sharpe, SignalRecord, run_backtest
from core.llm_router import normalized_overlap_ratio, trim_transcript_overlap
from models.request_models import MarketData


def test_momentum_score_normalizes_by_present_weights():
    score = _compute_momentum_score(MarketData(macd_signal=0.05))
    assert score == 0.5


def test_sharpe_uses_percent_returns_and_event_annualization():
    returns = np.array([5.0, -2.0, 4.0], dtype=float)
    expected = (np.mean(returns / 100.0) / np.std(returns / 100.0, ddof=1)) * math.sqrt(40.0)
    assert _calc_sharpe(returns, annual_events=40.0) == expected


def test_mdd_and_sharpe_share_percent_return_units():
    returns = np.array([4.0, -2.0, 1.0], dtype=float)
    assert _calc_mdd(returns) < 0.0
    assert _calc_sharpe(returns, annual_events=40.0) > 0.0


def test_zero_return_is_not_counted_as_loss():
    result = run_backtest(
        [
            SignalRecord(
                ticker="NVDA",
                timestamp=1741827000,
                composite_score=0.7,
                raw_score=0.6,
                trade_approved=True,
                strategy="GAP_AND_GO",
                actual_return=0.0,
            ),
            SignalRecord(
                ticker="AMD",
                timestamp=1741828000,
                composite_score=0.7,
                raw_score=0.6,
                trade_approved=True,
                strategy="GAP_AND_GO",
                actual_return=-1.0,
            ),
        ]
    )

    assert result.win_count == 1
    assert result.loss_count == 1


def test_overlap_ratio_handles_large_duplicate_window_linearly():
    previous = "A" * 4000 + "guidance raised"
    current = "guidance raised" + "B" * 4000
    assert normalized_overlap_ratio(previous, current) > 0.0
    assert trim_transcript_overlap(previous, current).startswith("B")
