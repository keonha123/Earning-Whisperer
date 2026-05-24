# MIT Quant Bible Application Notes

## Source Scope

Input reference:

- `MIT-Quant-Bible.pdf`

The document is mostly a quant interview and fundamentals guide. The directly useful project ideas are not new earnings strategies, but validation and sizing primitives:

- probability fundamentals
- confidence intervals
- Bayesian smoothing
- regression/regularization mindset
- Kelly sizing
- market-making spread, uncertainty, and execution-risk thinking

## Implemented Concepts

### 1. Wilson confidence lower bound

Plain win rate is unstable when sample count is small. The backtest metrics now include:

- `wilson_win_rate_lower_pct`

Promotion now requires the conservative Wilson lower bound to clear `45%`, so a strategy cannot be promoted only because the point estimate win rate looks good.

### 2. Bayesian win-rate smoothing

The metrics now include:

- `bayesian_win_rate_mean_pct`

This uses a simple beta-binomial prior so small samples do not overstate confidence.

### 3. Fractional Kelly sizing

The metrics now include:

- `fractional_kelly_pct`

This is bounded by `KELLY_MAX_POSITION` and uses the Bayesian win probability plus average win/loss payoff ratio. It is not used to auto-trade; it is a sizing diagnostic for research and front-office review.

### 4. Market-making style execution edge

The execution model now treats spread and latency as direct edge reducers. Conservative live/research paths block entries when:

- estimated all-in execution cost `>` `CONSERVATIVE_EXECUTION_COST_LIMIT_PCT`
- default limit: `0.55%`

This connects the project to a market-making principle: quoted/executed price must compensate for uncertainty and adverse movement risk.

## Backtest Result After Integration

Artifact:

- `data/backtests/nasdaq100_conservative_v957_quant_risk_20170120_20260426_proxy.json`

Summary:

| Metric | Value |
|---|---:|
| Trades | 43 |
| Win rate % | 62.7907 |
| Wilson lower % | 47.8595 |
| Bayesian win mean % | 62.2222 |
| Fractional Kelly % | 6.0587 |
| Avg trade return % | 0.6808 |
| Profit factor | 1.6782 |
| Sharpe | 2.2955 |
| MDD % | -11.4037 |
| Total return % | 31.2770 |

Promotion result:

- `prod_candidate`
- all conservative checks passed, including Wilson lower bound

## Engineering Files

- `core/quant_risk_math.py`
- `services/research_backtest_service.py`
- `tools/execution_stress_validate.py`
- `tests/test_quant_risk_math.py`
- `tests/test_research_backtest_service.py`

## Operating Interpretation

This upgrade makes the engine less likely to overfit to a lucky win-rate point estimate. The current Nasdaq100 conservative candidate remains attractive, but the confidence interval shows the statistically conservative win-rate floor is `47.8595%`, not `62.7907%`. That is the right framing for institutional review.
