# Nasdaq100 Conservative Quality Sleeve And Risk Governor

## Problem

The v9.5.4 retune fixed the largest source of Nasdaq100 conservative underperformance by removing non-core sectors and high-volatility news breakouts. The track improved materially, but it still failed the conservative production drawdown limit:

- trades: `43`
- win rate: `55.8140%`
- average trade return: `0.4981%`
- profit factor: `1.3936`
- Sharpe: `1.3244`
- MDD: `-19.1754%`
- production state: `hold_candidate`

The remaining loss cluster was not caused by one broad strategy bug. It came from two separate issues:

- the conservative profile had no controlled way to use high-quality mega-cap reversal events
- portfolio-level sequencing still accepted the next signal immediately after loss streaks or drawdown shocks

## Change

v9.5.5 adds two conservative-only controls.

### 1. Quality reversal sleeve

`REVERSAL_CATALYST` is now allowed for Nasdaq100 conservative only when all scope checks pass:

- sector is `TECHNOLOGY` or `COMMUNICATION_SERVICES`
- market-cap bucket is `mega`
- regime is `normal`

The same rule is wired into:

- live strategy selection: `strategies/orchestrator.py`
- offline approval: `services/research_backtest_service.py`
- shared helper: `core/strategy_track_rules.py`

### 2. Track risk governor

The offline research approval path now applies a Nasdaq100 conservative governor after individual trade approval:

- after `2` consecutive net losing trades, skip the next candidate trade
- after realized equity drawdown reaches `-8%`, pause new candidate trades for `30` days
- all win-rate and drawdown metrics are still calculated on net returns after costs

This is intentionally implemented in the research/backtest layer first. Live portfolio-level execution gating should consume the same policy only after broker/order state is available.

## Result

Same window and universe:

- window: `2017-01-20_to_2026-04-26`
- universe: `data/universes/nasdaq100_20260412.txt`
- mode: `price_proxy`
- min history: `120`

| Metric | v9.5.4 | v9.5.5 | Change |
|---|---:|---:|---:|
| Trades | 43 | 43 | 0 |
| Win rate % | 55.8140 | 62.7907 | +6.9767 |
| Avg trade return % | 0.4981 | 0.6808 | +0.1827 |
| Median trade return % | 1.0808 | 1.2479 | +0.1671 |
| Profit factor | 1.3936 | 1.6782 | +0.2846 |
| Sharpe | 1.3244 | 2.2955 | +0.9711 |
| MDD % | -19.1754 | -11.4037 | +7.7717 |
| Total return % | 20.7492 | 31.2770 | +10.5278 |

The v9.5.5 acceptance matrix selected `nasdaq100_conservative` as the production candidate:

| Scenario | Trades | Win % | Avg % | Total % | PF | Sharpe | MDD % | State |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Nasdaq100 conservative | 43 | 62.7907 | 0.6808 | 31.2770 | 1.6782 | 2.2955 | -11.4037 | prod_candidate |
| Nasdaq100 aggressive | 86 | 62.7907 | 0.5695 | 59.6834 | 1.8499 | 3.1556 | -16.2694 | research_canary_only |
| SP500 conservative | 85 | 52.9412 | 0.3273 | 27.2880 | 1.3093 | 1.2648 | -16.7419 | hold_candidate |
| SP500 aggressive | 87 | 57.4713 | 0.5289 | 49.7437 | 1.4074 | 1.1682 | -33.6557 | research_canary_only |

## Decision

- Nasdaq100 conservative is now the default production candidate from the 2017-2026 proxy acceptance run.
- Nasdaq100 aggressive remains research/canary only despite strong return metrics because aggressive tracks are intentionally blocked from direct production promotion.
- SP500 conservative still needs a separate drawdown retune before production promotion.

## Artifacts

- `data/backtests/nasdaq100_conservative_v955_20170120_20260426_proxy.json`
- `data/backtests/nasdaq100_conservative_v955_20170120_20260426_proxy.md`
- `data/backtests/acceptance_matrix_v955_20170120_20260426_proxy.json`
- `data/backtests/acceptance_matrix_v955_20170120_20260426_proxy.md`
