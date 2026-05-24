# Operation Readiness Validation

## Scope

This validation checks the v9.5.5 Nasdaq100 conservative production candidate before real-money use.

It separates three layers:

- `price_proxy`: broad-universe OHLCV/event proxy validation
- `event_replay`: persisted closed replay samples from PostgreSQL
- `execution_stress`: broker execution cost, spread, and latency stress on approved proxy trades

## Persisted Event Replay

Command:

```bash
python tools/market_interest_backtest.py --tickers-file data/universes/nasdaq100_20260412.txt --mode replay --use-database-replay --start-date 2017-01-20 --end-date 2026-04-26 --min-history 120 --universe-profile NASDAQ100 --risk-style CONSERVATIVE --output-json data/backtests/nasdaq100_conservative_v955_20170120_20260426_db_replay.json --output-md data/backtests/nasdaq100_conservative_v955_20170120_20260426_db_replay.md --quiet
```

Result:

- PostgreSQL connection: available
- `ai_events`: `1`
- `ai_analysis_runs`: `1`
- `ai_replay_tracks`: `1`
- closed `ai_replay_tracks`: `0`
- matched replay trades: `0`

Decision:

- Persisted replay validation is not yet statistically usable.
- The engine can now run DB-backed replay through `--use-database-replay`.
- Production approval must remain conditional until enough closed replay samples are accumulated.

## Execution Stress Validation

Command:

```bash
python tools/execution_stress_validate.py --input-json data/backtests/nasdaq100_conservative_v955_20170120_20260426_proxy.json --output-json data/backtests/nasdaq100_conservative_v955_execution_stress.json --output-md data/backtests/nasdaq100_conservative_v955_execution_stress.md --quiet
```

| Scenario | Total Cost % | Trades | Win % | Avg % | PF | Sharpe | MDD % | Passed |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| base_recomputed | 0.38 | 43 | 62.7907 | 0.6808 | 1.6782 | 2.2955 | -11.4038 | True |
| broker_normal | 0.55 | 43 | 58.1395 | 0.5108 | 1.4762 | 1.7223 | -13.2131 | True |
| earnings_gap_stress | 0.90 | 43 | 51.1628 | 0.1608 | 1.1315 | 0.5422 | -17.1412 | False |
| extreme_spread_stress | 1.40 | 43 | 51.1628 | -0.3392 | 0.7688 | -1.1436 | -26.5941 | False |

## Operating Decision

The current Nasdaq100 conservative candidate is suitable for controlled paper/live shadow operation under normal execution assumptions, not unrestricted real-money deployment.

Applied/required controls before broker execution:

- implemented: conservative live/research paths block entries when estimated all-in execution cost exceeds `0.55%`
- required for production: continue blocking new entries when spread/latency model implies `earnings_gap_stress`
- require persisted replay sample accumulation before final promotion
- maintain the v9.5.5 loss-streak/drawdown governor

## Artifacts

- `data/backtests/nasdaq100_conservative_v955_20170120_20260426_db_replay.json`
- `data/backtests/nasdaq100_conservative_v955_20170120_20260426_db_replay.md`
- `data/backtests/nasdaq100_conservative_v955_execution_stress.json`
- `data/backtests/nasdaq100_conservative_v955_execution_stress.md`
- `data/backtests/nasdaq100_conservative_v956_20170120_20260426_proxy.json`
- `data/backtests/nasdaq100_conservative_v956_20170120_20260426_proxy.md`
- `data/backtests/nasdaq100_conservative_v956_execution_stress.json`
- `data/backtests/nasdaq100_conservative_v956_execution_stress.md`
