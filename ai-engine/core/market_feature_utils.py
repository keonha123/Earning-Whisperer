"""Shared market feature calculations for live snapshots and proxy backtests."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def percentage_points(value: float | None) -> float:
    numeric = safe_float(value)
    if numeric is None:
        return 0.0
    return numeric * 100.0 if abs(numeric) <= 1.0 else numeric


def annualized_volatility(returns: pd.Series, window: int) -> float | None:
    if len(returns) < window:
        return None
    sample = returns.tail(window).dropna()
    if sample.empty:
        return None
    return float(sample.std(ddof=0) * math.sqrt(252.0))


def rolling_annualized_volatility(returns: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    min_count = min_periods if min_periods is not None else max(5, window // 2)
    return returns.rolling(window, min_periods=min_count).std().fillna(0.0) * math.sqrt(252.0)


def compute_rsi(close: pd.Series, period: int = 14) -> float | None:
    series = compute_rsi_series(close, period=period)
    if series.empty:
        return None
    return safe_float(series.iloc[-1])


def compute_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    avg_loss = avg_loss.replace(0.0, np.nan)
    rs = avg_gain / avg_loss
    return (100.0 - (100.0 / (1.0 + rs))).fillna(100.0)


def compute_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
    signal_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    rolling_low = low.rolling(period, min_periods=period).min()
    rolling_high = high.rolling(period, min_periods=period).max()
    denominator = (rolling_high - rolling_low).replace(0.0, np.nan)
    k = ((close - rolling_low) / denominator * 100.0).replace([np.inf, -np.inf], np.nan)
    d = k.rolling(signal_period, min_periods=signal_period).mean()
    return k, d


def compute_bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    mean = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std(ddof=0).replace(0.0, np.nan)
    upper = mean + (std * num_std)
    lower = mean - (std * num_std)
    width = (upper - lower).replace(0.0, np.nan)
    position = ((close - lower) / width).replace([np.inf, -np.inf], np.nan).clip(0.0, 1.0)
    bandwidth = (width / mean.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
    return upper, lower, position, bandwidth


def compute_atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=max(3, period // 2)).mean()


def compute_breakout_pct_series(close: pd.Series, lookback: int = 20) -> pd.Series:
    prior_high = close.shift(1).rolling(lookback, min_periods=max(10, lookback // 2)).max()
    return ((close / prior_high) - 1.0).replace([np.inf, -np.inf], np.nan)


def compute_breakout_pct(close: pd.Series, lookback: int = 20) -> float | None:
    series = compute_breakout_pct_series(close, lookback=lookback)
    if series.empty:
        return None
    return safe_float(series.iloc[-1])


def compute_volume_zscore(volume: pd.Series, lookback: int = 20) -> float | None:
    series = compute_volume_zscore_series(volume, lookback=lookback)
    if series.empty:
        return None
    return safe_float(series.iloc[-1])


def compute_volume_zscore_series(volume: pd.Series, lookback: int = 20) -> pd.Series:
    mean = volume.rolling(lookback, min_periods=max(10, lookback // 2)).mean()
    std = volume.rolling(lookback, min_periods=max(10, lookback // 2)).std(ddof=0).replace(0.0, np.nan)
    return ((volume - mean) / std).replace([np.inf, -np.inf], 0.0)


def compute_rolling_beta(asset_returns: pd.Series, benchmark_returns: pd.Series, window: int = 60) -> pd.Series:
    aligned = benchmark_returns.reindex(asset_returns.index).ffill()
    covariance = asset_returns.rolling(window, min_periods=max(20, window // 2)).cov(aligned)
    variance = aligned.rolling(window, min_periods=max(20, window // 2)).var(ddof=0).replace(0.0, np.nan)
    return (covariance / variance).replace([np.inf, -np.inf], np.nan)


def compute_relative_strength_vs_benchmark(close: pd.Series, benchmark_close: pd.Series, lookback: int = 20) -> pd.Series:
    asset_return = ((close / close.shift(lookback)) - 1.0) * 100.0
    benchmark_aligned = benchmark_close.reindex(close.index).ffill()
    benchmark_return = ((benchmark_aligned / benchmark_aligned.shift(lookback)) - 1.0) * 100.0
    return (asset_return - benchmark_return).replace([np.inf, -np.inf], np.nan)


def compute_weekly_ichimoku_series(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame(columns=["tenkan", "kijun", "span_a", "span_b", "score", "bias"])

    weekly = (
        history[["Open", "High", "Low", "Close"]]
        .resample("W-FRI")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        .dropna()
    )
    if len(weekly) < 80:
        return pd.DataFrame(columns=["tenkan", "kijun", "span_a", "span_b", "score", "bias"])

    high = weekly["High"].astype(float)
    low = weekly["Low"].astype(float)
    close = weekly["Close"].astype(float)

    tenkan = (high.rolling(9, min_periods=9).max() + low.rolling(9, min_periods=9).min()) / 2.0
    kijun = (high.rolling(26, min_periods=26).max() + low.rolling(26, min_periods=26).min()) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(26)
    span_b = ((high.rolling(52, min_periods=52).max() + low.rolling(52, min_periods=52).min()) / 2.0).shift(26)

    result = pd.DataFrame(
        {
            "tenkan": tenkan,
            "kijun": kijun,
            "span_a": span_a,
            "span_b": span_b,
            "close": close,
        }
    )

    def _row_score(row: pd.Series) -> float:
        if row[["close", "tenkan", "kijun", "span_a", "span_b"]].isna().any():
            return 0.0
        cloud_top = max(float(row["span_a"]), float(row["span_b"]))
        cloud_bottom = min(float(row["span_a"]), float(row["span_b"]))
        if float(row["close"]) > cloud_top and float(row["tenkan"]) >= float(row["kijun"]):
            return 1.0
        if float(row["close"]) < cloud_bottom and float(row["tenkan"]) <= float(row["kijun"]):
            return -1.0
        if float(row["close"]) > float(row["kijun"]):
            return 0.5
        if float(row["close"]) < float(row["kijun"]):
            return -0.5
        return 0.0

    result["score"] = result.apply(_row_score, axis=1)
    result["bias"] = result["score"].map(
        lambda value: "bullish" if value > 0 else ("bearish" if value < 0 else "neutral")
    )
    return result.drop(columns=["close"])


def compute_weekly_ichimoku_snapshot(history: pd.DataFrame) -> dict[str, float | str | None]:
    series = compute_weekly_ichimoku_series(history)
    if series.empty:
        return _empty_ichimoku_snapshot()

    last = series.iloc[-1]
    return {
        "tenkan": safe_float(last.get("tenkan")),
        "kijun": safe_float(last.get("kijun")),
        "span_a": safe_float(last.get("span_a")),
        "span_b": safe_float(last.get("span_b")),
        "bias": last.get("bias"),
        "score": safe_float(last.get("score")),
    }


def _empty_ichimoku_snapshot() -> dict[str, float | str | None]:
    return {
        "tenkan": None,
        "kijun": None,
        "span_a": None,
        "span_b": None,
        "bias": None,
        "score": None,
    }


__all__ = [
    "annualized_volatility",
    "compute_atr_series",
    "compute_bollinger",
    "compute_breakout_pct",
    "compute_breakout_pct_series",
    "compute_relative_strength_vs_benchmark",
    "compute_rsi",
    "compute_rsi_series",
    "compute_rolling_beta",
    "compute_stochastic",
    "compute_volume_zscore",
    "compute_volume_zscore_series",
    "compute_weekly_ichimoku_series",
    "compute_weekly_ichimoku_snapshot",
    "percentage_points",
    "rolling_annualized_volatility",
    "safe_float",
]
