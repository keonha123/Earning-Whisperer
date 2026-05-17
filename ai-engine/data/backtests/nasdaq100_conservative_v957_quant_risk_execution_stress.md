# Execution Stress Validation

- Source file: `data/backtests/nasdaq100_conservative_v957_quant_risk_20170120_20260426_proxy.json`
- Source mode: `price_proxy`
- Universe profile: `NASDAQ100`
- Risk style: `CONSERVATIVE`
- Source trade count: `43`

| Scenario | Total Cost % | Trades | Win % | Avg % | PF | Sharpe | MDD % | Passed |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| base_recomputed | 0.38 | 43 | 62.7907 | 0.6808 | 1.6782 | 2.2955 | -11.4038 | True |
| broker_normal | 0.55 | 43 | 58.1395 | 0.5108 | 1.4762 | 1.7223 | -13.2131 | True |
| earnings_gap_stress | 0.9 | 43 | 51.1628 | 0.1608 | 1.1315 | 0.5422 | -17.1412 | False |
| extreme_spread_stress | 1.4 | 43 | 51.1628 | -0.3392 | 0.7688 | -1.1436 | -26.5941 | False |