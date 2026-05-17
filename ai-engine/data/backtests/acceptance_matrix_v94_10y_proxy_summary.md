# EarningWhisperer v9.4 10Y Proxy Backtest Summary

- Run date: `2026-04-20`
- Period: `10y`
- Simulation mode: `price_proxy`
- Entry model: next trading day open
- Exit model: strategy `hold_days` + stop/take approximation
- Cost model: round-trip `0.30%` + default slippage `8bps`
- Source artifacts:
  - `data/backtests/acceptance_matrix_v94_10y_proxy.json`
  - `data/backtests/acceptance_matrix_v94_10y_proxy.md`

## Top-Level Results

| Scenario | Trades | Win Rate % | Avg Trade % | Profit Factor | Sharpe | Max DD % | Eligible |
|---|---:|---:|---:|---:|---:|---:|---|
| nasdaq100_conservative | 795 | 43.8994 | -0.1692 | 0.9073 | -0.4052 | -91.5271 | False |
| nasdaq100_aggressive | 1569 | 43.5946 | -0.2277 | 0.8713 | -0.5786 | -99.3404 | False |
| sp500_conservative | 2212 | 39.1049 | -0.4082 | 0.7840 | -0.9854 | -99.9978 | False |
| sp500_aggressive | 7325 | 41.3379 | -0.3714 | 0.7719 | -1.1021 | -100.0000 | False |

## Key Diagnostics

- Least-bad scenario was `nasdaq100_conservative`, but it still failed every promotion threshold.
- Aggressive variants increased trade count but worsened Sharpe and drawdown.
- Average gross return was only slightly positive for some scenarios, and the fixed cost drag of `0.38%` per trade flipped many marginal trades negative.
- `hold_days <= 2` was the dominant loss bucket across all four scenarios.
- `hold_days` buckets `4-6` were consistently positive, which suggests current runtime hold tuning is too short for proxy-event continuation trades.
- Stop-loss exits were the largest bucket and had an average net return near `-3.25%` to `-3.56%`.

## Strategy-Level Notes

- `nasdaq100_conservative`
  - `PEAD`: `575` trades, avg net `-0.1627%`
  - `NEWS_BREAKOUT`: `217` trades, avg net `-0.1364%`
- `nasdaq100_aggressive`
  - `PEAD`: `875` trades, avg net `-0.2625%`
  - `NEWS_BREAKOUT`: `493` trades, avg net `-0.2649%`
  - `REVERSAL_CATALYST`: `173` trades, avg net `+0.2124%`
  - `GAP_AND_GO`: `12` trades, avg net `+0.8130%`
- `sp500_conservative`
  - `PEAD`: `2185` trades, avg net `-0.4144%`
  - `GAP_AND_GO`: `27` trades, avg net `+0.0972%`
- `sp500_aggressive`
  - `GAP_AND_GO`: `60` trades, avg net `-0.6404%`
  - `REVERSAL_CATALYST`: `497` trades, avg net `-0.4303%`
  - `PEAD`: `3060` trades, avg net `-0.4031%`
  - `GAP_FILL`: `1254` trades, avg net `-0.3574%`
  - `NEWS_BREAKOUT`: `2454` trades, avg net `-0.3205%`

## Regime Notes

- `trend_up` was negative in every scenario and dominated trade volume.
- `normal` and `high_vol` were materially better, especially for Nasdaq.
- This points to continuation-style proxy entries being too permissive during broad uptrends.

## Fast What-If Filters

These are diagnostic subsets, not production portfolio results.

- `nasdaq100_conservative` with `hold_days >= 4`
  - trades `288`, win rate `55.56%`, avg trade `+0.4387%`, PF `1.3758`, MDD `-26.0493%`
- `nasdaq100_aggressive` with `hold_days >= 4`
  - trades `470`, win rate `56.60%`, avg trade `+0.4695%`, PF `1.4128`, MDD `-30.3592%`
- `sp500_conservative` with `hold_days >= 4`
  - trades `832`, win rate `52.04%`, avg trade `+0.4024%`, PF `1.3512`, MDD `-43.6417%`
- `sp500_aggressive` with `hold_days >= 4`
  - trades `1756`, win rate `54.56%`, avg trade `+0.4222%`, PF `1.4201`, MDD `-52.2781%`

## Immediate Engineering Implications

- Raise the minimum effective hold window for continuation-style proxy trades.
- Tighten gate quality filters in `trend_up` regime instead of relaxing thresholds.
- Reduce or suspend `PEAD` on the broad SP500 profile until segment-level calibration is in place.
- Add explicit portfolio-capital constraints before treating total return as deployable portfolio CAGR.
