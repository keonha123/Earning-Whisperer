# Nasdaq100 Conservative Retune

## Problem

The 2017-01-20 to 2026-04-26 proxy backtest showed that Nasdaq100 conservative was too broadly selective:

- It approved only `70` trades out of more than `10,000` candidates.
- Approved non-core sectors diluted the edge.
- High-volatility `NEWS_BREAKOUT` trades contained several large stop-loss events.
- The old result had positive expectancy but weak practical quality:
  - win rate: `48.5714%`
  - average trade: `0.1008%`
  - median trade: `-0.4710%`
  - profit factor: `1.0654`
  - Sharpe: `0.2533`
  - MDD: `-29.5416%`
  - total return: `2.4619%`

## Change

The retune keeps the conservative track strict and does not relax thresholds.

Added Nasdaq100 conservative blockers:

- `nasdaq_conservative_non_core_sector`
  - Allows only `TECHNOLOGY` and `COMMUNICATION_SERVICES` when sector metadata is available.
  - Missing sector metadata degrades safely and does not block.
- `nasdaq_conservative_high_vol_news_breakout`
  - Blocks `NEWS_BREAKOUT` when the regime is `high_vol`.

These rules are wired into both:

- live strategy selection in `strategies/orchestrator.py`
- offline approval logic in `services/research_backtest_service.py`

## Result

Same window and universe:

- window: `2017-01-20_to_2026-04-26`
- universe: `data/universes/nasdaq100_20260412.txt`
- mode: `price_proxy`
- min history: `120`

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Trades | 70 | 43 | -27 |
| Win rate % | 48.5714 | 55.8140 | +7.2426 |
| Avg trade return % | 0.1008 | 0.4981 | +0.3973 |
| Median trade return % | -0.4710 | 1.0808 | +1.5518 |
| Profit factor | 1.0654 | 1.3936 | +0.3282 |
| Sharpe | 0.2533 | 1.3244 | +1.0711 |
| MDD % | -29.5416 | -19.1754 | +10.3662 |
| Total return % | 2.4619 | 20.7492 | +18.2873 |

## Segment Quality After Retune

By sector:

- `COMMUNICATION_SERVICES`: `13` trades, `61.5385%` win rate, `0.5878%` avg trade, `-4.1636%` MDD
- `TECHNOLOGY`: `30` trades, `53.3333%` win rate, `0.4592%` avg trade, `-18.3561%` MDD

By market-cap bucket:

- `mega`: `26` trades, `57.6923%` win rate, `0.7669%` avg trade, `-9.8425%` MDD
- `large`: `17` trades, `52.9412%` win rate, `0.0870%` avg trade, `-12.8673%` MDD

## Decision

- Production promotion: `not yet`
- Candidate status: `hold_candidate`
- Reason: all core return-quality metrics improved, but MDD remains above the conservative `-12%` production limit.
- Next improvement target: large-cap Nasdaq technology risk control, because `mega` already satisfies the drawdown target while keeping strong expectancy.
