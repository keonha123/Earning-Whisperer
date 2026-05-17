from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any

import pandas as pd
import yfinance as yf

try:
    from core.market_feature_utils import (
        annualized_volatility,
        compute_atr_series,
        compute_bollinger,
        compute_breakout_pct,
        compute_relative_strength_vs_benchmark,
        compute_rsi,
        compute_rolling_beta,
        compute_stochastic,
        compute_volume_zscore,
        compute_weekly_ichimoku_snapshot,
        percentage_points,
        safe_float,
    )
    from models.request_models import MarketData
except ImportError:  # pragma: no cover
    from ..core.market_feature_utils import (
        annualized_volatility,
        compute_atr_series,
        compute_bollinger,
        compute_breakout_pct,
        compute_relative_strength_vs_benchmark,
        compute_rsi,
        compute_rolling_beta,
        compute_stochastic,
        compute_volume_zscore,
        compute_weekly_ichimoku_snapshot,
        percentage_points,
        safe_float,
    )
    from ..models.request_models import MarketData


def _market_cap_bucket(market_cap: float | None) -> str | None:
    numeric = safe_float(market_cap)
    if numeric is None:
        return None
    if numeric >= 200_000_000_000:
        return "mega"
    if numeric >= 10_000_000_000:
        return "large"
    if numeric >= 2_000_000_000:
        return "mid"
    if numeric >= 300_000_000:
        return "small"
    return "micro"


def _percentage_or_none(value: Any) -> float | None:
    numeric = safe_float(value)
    if numeric is None:
        return None
    return percentage_points(numeric)


def _extract_history(frame: pd.DataFrame | None, ticker: str) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = set(frame.columns.get_level_values(0))
        level1 = set(frame.columns.get_level_values(1))
        if ticker in level0:
            extracted = frame[ticker]
        elif ticker in level1:
            extracted = frame.xs(ticker, axis=1, level=1)
        else:
            return None
    else:
        extracted = frame
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(extracted.columns)):
        return None
    return extracted.dropna(subset=list(required)).copy()


def _clear_proxy_env() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "GIT_HTTP_PROXY",
        "GIT_HTTPS_PROXY",
        "git_http_proxy",
        "git_https_proxy",
    ):
        os.environ.pop(key, None)


def _download_benchmark_histories(period: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    _clear_proxy_env()
    try:
        frame = yf.download(
            tickers=["SPY", "QQQ"],
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    except Exception:
        return None, None
    return _extract_history(frame, "SPY"), _extract_history(frame, "QQQ")


def _summarize_zero_dte_options(ticker_obj: yf.Ticker, current_price: float | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "has_options": None,
        "nearest_option_expiry_days": None,
        "zero_dte_available": None,
        "zero_dte_put_call_volume_ratio": None,
        "zero_dte_atm_straddle_pct": None,
        "zero_dte_gamma_pressure": None,
    }

    try:
        expiries = list(getattr(ticker_obj, "options", []) or [])
    except Exception:
        return payload
    if not expiries:
        payload["has_options"] = False
        return payload

    payload["has_options"] = True
    today = datetime.now(UTC).date()
    dated: list[tuple[str, int]] = []
    for expiry in expiries:
        try:
            delta = (pd.Timestamp(expiry).date() - today).days
        except Exception:
            continue
        if delta >= 0:
            dated.append((expiry, delta))
    if not dated:
        return payload

    nearest_expiry, nearest_days = min(dated, key=lambda item: item[1])
    payload["nearest_option_expiry_days"] = int(nearest_days)
    payload["zero_dte_available"] = nearest_days == 0
    if nearest_days != 0:
        return payload

    try:
        chain = ticker_obj.option_chain(nearest_expiry)
    except Exception:
        return payload
    calls = getattr(chain, "calls", None)
    puts = getattr(chain, "puts", None)
    if calls is None or puts is None or calls.empty or puts.empty:
        return payload

    call_volume = float(calls.get("volume", pd.Series(dtype=float)).fillna(0.0).sum())
    put_volume = float(puts.get("volume", pd.Series(dtype=float)).fillna(0.0).sum())
    if call_volume > 0:
        payload["zero_dte_put_call_volume_ratio"] = round(put_volume / call_volume, 4)

    if current_price is not None and current_price > 0:
        calls = calls.copy()
        puts = puts.copy()
        calls["distance"] = (calls["strike"].astype(float) - current_price).abs()
        puts["distance"] = (puts["strike"].astype(float) - current_price).abs()
        atm_call = calls.sort_values("distance").head(1)
        atm_put = puts.sort_values("distance").head(1)
        if not atm_call.empty and not atm_put.empty:
            call_mid = safe_float(atm_call.iloc[0].get("lastPrice")) or safe_float(atm_call.iloc[0].get("ask")) or 0.0
            put_mid = safe_float(atm_put.iloc[0].get("lastPrice")) or safe_float(atm_put.iloc[0].get("ask")) or 0.0
            payload["zero_dte_atm_straddle_pct"] = round(((call_mid + put_mid) / current_price) * 100.0, 4)

    call_oi = float(calls.get("openInterest", pd.Series(dtype=float)).fillna(0.0).sum())
    put_oi = float(puts.get("openInterest", pd.Series(dtype=float)).fillna(0.0).sum())
    total_oi = call_oi + put_oi
    if total_oi > 0:
        payload["zero_dte_gamma_pressure"] = round((call_oi - put_oi) / total_oi, 4)

    return payload


def get_market_data(ticker: str) -> dict[str, Any]:
    symbol = ticker.upper()
    _clear_proxy_env()
    ticker_obj = yf.Ticker(symbol)
    try:
        info = ticker_obj.info or {}
    except Exception:
        info = {}
    try:
        hist = ticker_obj.history(period="2y", interval="1d", auto_adjust=False)
    except Exception:
        hist = None

    if hist is None or hist.empty:
        return {
            "ticker": symbol,
            "price": None,
            "prev_close": None,
            "volume_ratio": None,
            "avg_volume_20d": None,
            "rsi_14": None,
            "realized_vol_10d": None,
            "atr_pct_14": None,
            "atr_14": None,
            "market_cap": None,
            "bb_position": None,
            "bb_bandwidth": None,
            "ma20": None,
            "ma50": None,
            "ma200": None,
            "stochastic_k": None,
            "stochastic_d": None,
            "ichimoku_weekly_cloud_bias": None,
            "spy_relative_strength_20d": None,
            "qqq_relative_strength_20d": None,
            "beta_spy_60d": None,
            "beta_qqq_60d": None,
            "revenue_growth_yoy": None,
            "earnings_growth_yoy": None,
            "gross_margin": None,
            "operating_margin": None,
            "fcf_margin": None,
            "debt_to_equity": None,
            "current_ratio": None,
            "has_options": None,
        }

    hist = hist.dropna(subset=["Open", "High", "Low", "Close", "Volume"]).copy()
    close = hist["Close"].astype(float)
    high = hist["High"].astype(float)
    low = hist["Low"].astype(float)
    volume = hist["Volume"].fillna(0.0).astype(float)
    returns = close.pct_change().dropna()

    last_price = safe_float(close.iloc[-1])
    prev_close = safe_float(close.iloc[-2]) if len(close) >= 2 else None
    avg_volume_20d = safe_float(volume.tail(20).mean())
    last_volume = safe_float(volume.iloc[-1])
    open_price = safe_float(hist["Open"].iloc[-1])
    gap_pct = (((open_price / prev_close) - 1.0) * 100.0) if open_price and prev_close else None

    rsi_14 = compute_rsi(close, 14)
    stoch_k, stoch_d = compute_stochastic(high, low, close, period=14, signal_period=3)
    _, _, bb_position, bb_bandwidth = compute_bollinger(close, period=20, num_std=2.0)
    atr_14_series = compute_atr_series(high, low, close, period=14)
    atr_14 = safe_float(atr_14_series.iloc[-1]) if not atr_14_series.empty else None
    atr_pct_14 = ((atr_14 / last_price) * 100.0) if atr_14 is not None and last_price else None

    spy_hist, qqq_hist = _download_benchmark_histories("2y")
    spy_close = spy_hist["Close"].astype(float) if spy_hist is not None and not spy_hist.empty else None
    qqq_close = qqq_hist["Close"].astype(float) if qqq_hist is not None and not qqq_hist.empty else None
    asset_returns = close.pct_change().fillna(0.0)
    beta_spy = compute_rolling_beta(asset_returns, spy_close.pct_change().fillna(0.0), 60) if spy_close is not None else pd.Series(dtype=float)
    beta_qqq = compute_rolling_beta(asset_returns, qqq_close.pct_change().fillna(0.0), 60) if qqq_close is not None else pd.Series(dtype=float)
    spy_relative = compute_relative_strength_vs_benchmark(close, spy_close, 20) if spy_close is not None else pd.Series(dtype=float)
    qqq_relative = compute_relative_strength_vs_benchmark(close, qqq_close, 20) if qqq_close is not None else pd.Series(dtype=float)

    ichimoku = compute_weekly_ichimoku_snapshot(hist)

    total_revenue = safe_float(info.get("totalRevenue"))
    free_cash_flow = safe_float(info.get("freeCashflow"))
    fcf_margin = ((free_cash_flow / total_revenue) * 100.0) if free_cash_flow is not None and total_revenue else None

    option_snapshot = _summarize_zero_dte_options(ticker_obj, last_price)

    ma20 = safe_float(close.tail(20).mean()) if len(close) >= 20 else None
    ma50 = safe_float(close.tail(50).mean()) if len(close) >= 50 else None
    ma200 = safe_float(close.tail(200).mean()) if len(close) >= 200 else None
    ma_stack_bullish = None
    if last_price is not None and None not in (ma20, ma50, ma200):
        ma_stack_bullish = bool(last_price > ma20 > ma50 > ma200)

    market_cap = safe_float(info.get("marketCap"))
    sector = str(info.get("sector") or info.get("industryKey") or "unknown").upper().replace(" ", "_")

    result = {
        "ticker": symbol,
        "price": last_price,
        "prev_close": prev_close,
        "high_52w": safe_float(info.get("fiftyTwoWeekHigh")) or safe_float(close.tail(252).max()),
        "low_52w": safe_float(info.get("fiftyTwoWeekLow")) or safe_float(close.tail(252).min()),
        "market_cap": market_cap,
        "market_cap_bucket": _market_cap_bucket(market_cap),
        "sector_code": sector,
        "beta": safe_float(info.get("beta")),
        "beta_spy_60d": safe_float(beta_spy.iloc[-1]) if not beta_spy.empty else None,
        "beta_qqq_60d": safe_float(beta_qqq.iloc[-1]) if not beta_qqq.empty else None,
        "trailing_pe": safe_float(info.get("trailingPE")),
        "forward_pe": safe_float(info.get("forwardPE")),
        "current_iv": safe_float(info.get("impliedVolatility")),
        "volume_ratio": (last_volume / avg_volume_20d) if last_volume and avg_volume_20d else None,
        "avg_volume_20d": avg_volume_20d,
        "rsi_14": rsi_14,
        "stochastic_k": safe_float(stoch_k.iloc[-1]) if not stoch_k.empty else None,
        "stochastic_d": safe_float(stoch_d.iloc[-1]) if not stoch_d.empty else None,
        "realized_vol_10d": annualized_volatility(returns, 10),
        "atr_pct_14": atr_pct_14,
        "atr_14": atr_14,
        "gap_pct": gap_pct,
        "breakout_20d_pct": compute_breakout_pct(close, 20),
        "volume_zscore_20d": compute_volume_zscore(volume, 20),
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "ma_stack_bullish": ma_stack_bullish,
        "bb_position": safe_float(bb_position.iloc[-1]) if not bb_position.empty else None,
        "bb_bandwidth": safe_float(bb_bandwidth.iloc[-1]) if not bb_bandwidth.empty else None,
        "relative_strength_20d": ((last_price / float(close.iloc[-21])) - 1.0) * 100.0 if last_price and len(close) >= 21 else None,
        "spy_relative_strength_20d": safe_float(spy_relative.iloc[-1]) if not spy_relative.empty else None,
        "qqq_relative_strength_20d": safe_float(qqq_relative.iloc[-1]) if not qqq_relative.empty else None,
        "ichimoku_weekly_tenkan": ichimoku["tenkan"],
        "ichimoku_weekly_kijun": ichimoku["kijun"],
        "ichimoku_weekly_span_a": ichimoku["span_a"],
        "ichimoku_weekly_span_b": ichimoku["span_b"],
        "ichimoku_weekly_cloud_bias": ichimoku["bias"],
        "ichimoku_weekly_cloud_score": safe_float(ichimoku["score"]),
        "revenue_growth_yoy": _percentage_or_none(info.get("revenueGrowth")),
        "earnings_growth_yoy": _percentage_or_none(info.get("earningsGrowth")),
        "gross_margin": _percentage_or_none(info.get("grossMargins")),
        "operating_margin": _percentage_or_none(info.get("operatingMargins")),
        "fcf_margin": fcf_margin,
        "debt_to_equity": safe_float(info.get("debtToEquity")),
        "current_ratio": safe_float(info.get("currentRatio")),
        **option_snapshot,
    }
    return result


def build_market_data_snapshot(ticker: str, overrides: dict[str, Any] | None = None) -> MarketData:
    raw = get_market_data(ticker)
    merged = {
        "ticker": ticker.upper(),
        "current_price": raw.get("price"),
        "prev_close": raw.get("prev_close"),
        "gap_pct": raw.get("gap_pct") or 0.0,
        "surprise_pct": 0.0,
        "post_earnings_drift_pct": raw.get("relative_strength_20d") or 0.0,
        "short_interest_pct_float": 0.0,
        "float_rotation": 0.0,
        "days_to_cover": 0.0,
        "iv_rank": 0.0,
        "current_iv": raw.get("current_iv") or 0.0,
        "implied_move_pct": raw.get("zero_dte_atm_straddle_pct"),
        "bid_ask_spread_bps": None,
        "day1_return_pct": 0.0,
        "volume_ratio": raw.get("volume_ratio") or 1.0,
        "relative_strength_20d": raw.get("relative_strength_20d") or 0.0,
        "sector_momentum": 0.0,
        "vix": 20.0,
        "beta_20d": raw.get("beta") or 1.0,
        "liquidity_score": 0.5,
        "next_earnings_days": 30,
        "rsi_14": raw.get("rsi_14") or 50.0,
        "analyst_revision_delta_pct": 0.0,
        "hours_since_news": None,
        "realized_vol_10d": raw.get("realized_vol_10d"),
        "atr_pct_14": raw.get("atr_pct_14"),
        "atr_14": raw.get("atr_14"),
        "breakout_20d_pct": raw.get("breakout_20d_pct"),
        "high_52w": raw.get("high_52w"),
        "low_52w": raw.get("low_52w"),
        "ma20": raw.get("ma20"),
        "ma50": raw.get("ma50"),
        "ma200": raw.get("ma200"),
        "ma_stack_bullish": raw.get("ma_stack_bullish"),
        "bb_position": raw.get("bb_position"),
        "bb_bandwidth": raw.get("bb_bandwidth"),
        "stochastic_k": raw.get("stochastic_k"),
        "stochastic_d": raw.get("stochastic_d"),
        "ichimoku_weekly_tenkan": raw.get("ichimoku_weekly_tenkan"),
        "ichimoku_weekly_kijun": raw.get("ichimoku_weekly_kijun"),
        "ichimoku_weekly_span_a": raw.get("ichimoku_weekly_span_a"),
        "ichimoku_weekly_span_b": raw.get("ichimoku_weekly_span_b"),
        "ichimoku_weekly_cloud_bias": raw.get("ichimoku_weekly_cloud_bias"),
        "ichimoku_weekly_cloud_score": raw.get("ichimoku_weekly_cloud_score"),
        "volume_zscore_20d": raw.get("volume_zscore_20d"),
        "spy_relative_strength_20d": raw.get("spy_relative_strength_20d"),
        "qqq_relative_strength_20d": raw.get("qqq_relative_strength_20d"),
        "beta_spy_60d": raw.get("beta_spy_60d"),
        "beta_qqq_60d": raw.get("beta_qqq_60d"),
        "nearest_option_expiry_days": raw.get("nearest_option_expiry_days"),
        "zero_dte_available": raw.get("zero_dte_available"),
        "zero_dte_put_call_volume_ratio": raw.get("zero_dte_put_call_volume_ratio"),
        "zero_dte_atm_straddle_pct": raw.get("zero_dte_atm_straddle_pct"),
        "zero_dte_gamma_pressure": raw.get("zero_dte_gamma_pressure"),
        "revenue_growth_yoy": raw.get("revenue_growth_yoy"),
        "earnings_growth_yoy": raw.get("earnings_growth_yoy"),
        "gross_margin": raw.get("gross_margin"),
        "operating_margin": raw.get("operating_margin"),
        "fcf_margin": raw.get("fcf_margin"),
        "debt_to_equity": raw.get("debt_to_equity"),
        "current_ratio": raw.get("current_ratio"),
        "market_cap": raw.get("market_cap"),
        "market_cap_bucket": raw.get("market_cap_bucket"),
        "sector_code": raw.get("sector_code"),
        "has_options": raw.get("has_options"),
    }
    if overrides:
        merged.update(overrides)
    return MarketData.model_validate(merged)


__all__ = ["get_market_data", "build_market_data_snapshot"]
