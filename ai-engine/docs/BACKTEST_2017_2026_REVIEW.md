# Backtest Review: 2017-01-20 to 2026-04-26

## Scope

- Universe files:
  - `data/universes/nasdaq100_20260412.txt`
  - `data/universes/sp500_20260412.txt`
- Mode: `price_proxy`
- Window: `2017-01-20_to_2026-04-26`
- Minimum history: `120` trading sessions
- Entry rule: next-session open after signal bar
- Exit rule: strategy hold-days with daily high/low stop/take approximation
- Cost rule: net return after configured round-trip cost and slippage

## Command

```bash
python tools/market_interest_backtest.py --acceptance-matrix --mode proxy --start-date 2017-01-20 --end-date 2026-04-26 --min-history 120 --nasdaq-file data/universes/nasdaq100_20260412.txt --sp500-file data/universes/sp500_20260412.txt --output-json data/backtests/acceptance_matrix_v952_20170120_20260426_proxy_rerun.json --output-md data/backtests/acceptance_matrix_v952_20170120_20260426_proxy_rerun.md --quiet
```

## Result Summary

| Scenario | Trades | Win Rate % | Avg Return % | Total Return % | Benchmark % | Profit Factor | Sharpe | MDD % | State | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| nasdaq100_conservative | 70 | 48.5714 | 0.1008 | 2.4619 | 480.3710 | 1.0654 | 0.2533 | -29.5416 | hold_candidate | False |
| nasdaq100_aggressive | 86 | 62.7907 | 0.5695 | 59.6834 | 480.3710 | 1.8499 | 3.1556 | -16.2694 | research_canary_only | False |
| sp500_conservative | 85 | 52.9412 | 0.3273 | 27.2880 | 247.2244 | 1.3093 | 1.2648 | -16.7419 | hold_candidate | False |
| sp500_aggressive | 87 | 57.4713 | 0.5289 | 49.7437 | 247.2244 | 1.4074 | 1.1682 | -33.6557 | research_canary_only | False |

## Interpretation

- `sp500_conservative` remains the best production-candidate track because it has positive expectancy, profit factor above `1.15`, and Sharpe above `1.0`.
- `sp500_conservative` still fails production promotion because win rate is just below the `53%` threshold and MDD is worse than the `-12%` conservative limit.
- `nasdaq100_aggressive` passes the aggressive research thresholds, but the system intentionally keeps aggressive tracks as `research_canary_only`.
- `sp500_aggressive` has positive expectancy but fails the aggressive MDD threshold.
- Benchmark returns are buy-and-hold universe proxy returns and are not directly comparable to strategy total return because strategy exposure is sparse and event-gated.

## Engineering Notes

- The first long-run acceptance command wrote valid artifacts but did not exit cleanly in this Windows/Python 3.13 environment.
- The yfinance batch downloader now uses `threads=False` to avoid worker-thread exit hangs after report generation.
- The rerun completed normally and matched the first artifact exactly on core scenario metrics.

## Promotion Decision

- Production promotion: `none`
- Best hold candidate: `sp500_conservative`
- Research/canary candidate: `nasdaq100_aggressive`
- Required next improvement:
  - reduce conservative MDD below `12%`
  - push `sp500_conservative` win rate above `53%`
  - keep aggressive tracks out of production until replay-ground validation confirms proxy results
