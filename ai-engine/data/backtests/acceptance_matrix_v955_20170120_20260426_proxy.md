# EarningWhisperer v9.4 Acceptance Matrix

- Generated at: `2026-04-27T13:48:21.000124+00:00`
- Simulation mode: `proxy`
- Data window: `2017-01-20_to_2026-04-26`
- Selected prod candidate: `nasdaq100_conservative`

| Scenario | Trades | Win Rate % | Avg Return % | Total Return % | Benchmark % | Profit Factor | Sharpe | MDD % | State | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| nasdaq100_conservative | 43 | 62.7907 | 0.6808 | 31.277 | 480.371 | 1.6782 | 2.2955 | -11.4037 | prod_candidate | True |
| nasdaq100_aggressive | 86 | 62.7907 | 0.5695 | 59.6834 | 480.371 | 1.8499 | 3.1556 | -16.2694 | research_canary_only | False |
| sp500_conservative | 85 | 52.9412 | 0.3273 | 27.288 | 247.2244 | 1.3093 | 1.2648 | -16.7419 | hold_candidate | False |
| sp500_aggressive | 87 | 57.4713 | 0.5289 | 49.7437 | 247.2244 | 1.4074 | 1.1682 | -33.6557 | research_canary_only | False |