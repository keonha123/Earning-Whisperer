"""Backtesting and operating-mode helpers for earnings-event strategies."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import get_settings

DEFAULT_ANNUAL_EVENTS = 40.0


@dataclass
class SignalRecord:
    """Single signal record used in research and backtests."""

    ticker: str
    timestamp: int
    composite_score: float
    raw_score: float
    trade_approved: bool
    strategy: str
    actual_return: Optional[float] = None


@dataclass
class BacktestResult:
    """Summary statistics produced by a research run."""

    total_signals: int
    approved_signals: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_return: float
    sharpe_ratio: float
    max_drawdown: float
    strategy_stats: Dict[str, dict]
    gate_approval_rate: float
    avg_trades_per_day: float
    target_win_rate: float
    meets_target_win_rate: bool

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def run_backtest(records: List[SignalRecord]) -> BacktestResult:
    """Run a basic event-driven backtest from signal records."""

    if not records:
        return _empty_result()

    settings = get_settings()
    approved = [record for record in records if record.trade_approved]
    with_return = [record for record in approved if record.actual_return is not None]

    win_count = sum(1 for record in with_return if (record.actual_return or 0.0) >= 0.0)
    loss_count = sum(1 for record in with_return if (record.actual_return or 0.0) < 0.0)
    win_rate = win_count / len(with_return) if with_return else 0.0

    returns = np.array([record.actual_return for record in with_return], dtype=float)
    avg_return = float(np.mean(returns)) if len(returns) > 0 else 0.0
    annual_events = _estimate_annual_events(with_return)

    sharpe = _calc_sharpe(returns, annual_events=annual_events)
    mdd = _calc_mdd(returns)
    strategy_stats = _calc_strategy_stats(with_return)
    gate_approval_rate = len(approved) / len(records) if records else 0.0
    avg_trades_per_day = _calc_avg_trades_per_day(approved)
    meets_target = win_rate >= settings.execution_target_win_rate if with_return else False

    return BacktestResult(
        total_signals=len(records),
        approved_signals=len(approved),
        win_count=win_count,
        loss_count=loss_count,
        win_rate=round(win_rate, 4),
        avg_return=round(avg_return, 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown=round(mdd, 4),
        strategy_stats=strategy_stats,
        gate_approval_rate=round(gate_approval_rate, 4),
        avg_trades_per_day=round(avg_trades_per_day, 4),
        target_win_rate=settings.execution_target_win_rate,
        meets_target_win_rate=meets_target,
    )


def recommend_gate_adjustment(result: BacktestResult) -> Tuple[str, str]:
    """Recommend threshold changes from research results."""

    sample_size = result.win_count + result.loss_count
    if sample_size < 10:
        return "hold", f"Sample size too small ({sample_size} < 10)."

    if result.win_rate < 0.45:
        return (
            "tighten",
            "Win rate below 45%; raise composite/confidence thresholds and demand better liquidity.",
        )

    if result.win_rate > 0.60 and sample_size >= 30:
        return (
            "loosen",
            "Win rate above 60% with enough samples; selective loosening is reasonable.",
        )

    return "hold", "Current thresholds are within a stable operating range."


def recommend_operating_mode(result: BacktestResult) -> Dict[str, object]:
    """Translate backtest statistics into practical trading cadence guidance."""

    if result.avg_trades_per_day >= 6 and result.win_rate >= result.target_win_rate:
        mode = "INTRADAY_EVENT"
        rationale = "The strategy is active enough for repeated intraday event trades."
    elif result.avg_trades_per_day >= 1 and result.win_rate >= result.target_win_rate:
        mode = "EVENT_SWING"
        rationale = "Trade frequency and edge fit one-to-three-day event swing trading."
    else:
        mode = "SELECTIVE_SWING"
        rationale = "Frequency and quality do not support HFT; keep a selective lower-frequency stance."

    return {
        "mode": mode,
        "avg_trades_per_day": result.avg_trades_per_day,
        "rationale": rationale,
    }


def _calc_sharpe(
    returns: np.ndarray,
    *,
    risk_free: float = 0.0,
    annual_events: float = DEFAULT_ANNUAL_EVENTS,
) -> float:
    """Compute event-based Sharpe from percentage returns."""

    if len(returns) < 2:
        return 0.0

    returns_decimal = returns / 100.0
    excess = returns_decimal - risk_free
    std = np.std(excess, ddof=1)
    if std < 1e-10:
        return 0.0
    return float(np.mean(excess) / std * math.sqrt(max(annual_events, 1.0)))


def _calc_mdd(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    cumulative = np.cumprod(1.0 + returns / 100.0)
    rolling_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - rolling_max) / rolling_max * 100
    return float(np.min(drawdowns))


def _calc_strategy_stats(records: List[SignalRecord]) -> Dict[str, dict]:
    stats: Dict[str, list[SignalRecord]] = {}
    for record in records:
        stats.setdefault(record.strategy, []).append(record)

    result = {}
    for strategy, strategy_records in stats.items():
        returns = [record.actual_return or 0.0 for record in strategy_records]
        arr = np.array(returns, dtype=float)
        wins = sum(1 for value in returns if value >= 0.0)
        result[strategy] = {
            "count": len(returns),
            "win_rate": round(wins / len(returns), 4) if returns else 0.0,
            "avg_return": round(float(np.mean(arr)), 4) if len(arr) else 0.0,
            "sharpe": round(
                _calc_sharpe(arr, annual_events=_estimate_annual_events(strategy_records)),
                4,
            ),
        }
    return result


def _estimate_annual_events(records: List[SignalRecord]) -> float:
    """Estimate yearly event frequency from timestamps, capped by the event-trading default."""

    if len(records) < 2:
        return DEFAULT_ANNUAL_EVENTS

    timestamps = sorted(record.timestamp for record in records)
    span_seconds = max(timestamps[-1] - timestamps[0], 1)
    years_spanned = max(span_seconds / (365.25 * 24 * 60 * 60), 1.0)
    observed_events = len(records) / years_spanned
    return min(max(observed_events, 1.0), DEFAULT_ANNUAL_EVENTS)


def _calc_avg_trades_per_day(records: List[SignalRecord]) -> float:
    if not records:
        return 0.0
    days = {}
    for record in records:
        day = datetime.fromtimestamp(record.timestamp, UTC).date().isoformat()
        days[day] = days.get(day, 0) + 1
    return sum(days.values()) / len(days)


def _empty_result() -> BacktestResult:
    settings = get_settings()
    return BacktestResult(
        total_signals=0,
        approved_signals=0,
        win_count=0,
        loss_count=0,
        win_rate=0.0,
        avg_return=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        strategy_stats={},
        gate_approval_rate=0.0,
        avg_trades_per_day=0.0,
        target_win_rate=settings.execution_target_win_rate,
        meets_target_win_rate=False,
    )
