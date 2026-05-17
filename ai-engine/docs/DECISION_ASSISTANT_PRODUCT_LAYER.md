# Decision Assistant Product Layer

## Purpose

The Decision Assistant turns raw signal output into a product-grade buy/sell judgment layer. It is designed to differentiate EarningWhisperer from retail brokerage AI summaries by answering four practical questions:

- Should the user buy, hold, reduce, exit, or avoid?
- If the trade is blocked, exactly why is it blocked?
- Is the signal backed by replay/backtest evidence?
- Is the trade executable after spread, latency, and transaction cost?

This layer is advisory-only. It does not call KIS, broker, or order execution APIs.

## Output Location

The payload is additive and does not remove or rename existing fields.

- `metadata.decision_assistant`
- `metadata.product_surface.decision_assistant`
- `metadata.product_surface.front_payload_ko.decision_assistant`
- `metadata.product_surface.frontend_contract_ko.decision_assistant`
- `data.analysis.decision_assistant`
- `data.cards[].card_type == "decision_assistant"`
- `signal_brief.sell_first_action`
- `signal_brief.replay_confidence_badge`
- `signal_brief.execution_badge`

## Main Blocks

### Sell-First Guidance

`sell_first` returns a portfolio-action view:

- `ADD`: signal is strong enough to consider adding exposure
- `HOLD`: keep current exposure and wait for confirmation
- `REDUCE`: reduce risk due to signal decay, hard blockers, or weak technical/fundamental state
- `EXIT`: bearish hard-risk setup with high magnitude/confidence
- `AVOID`: no new entry because execution cost, gate failure, or hard risk dominates

### No-Trade Explainer

`no_trade_explainer` returns:

- `blocked`
- `deny_summary_ko`
- `blocked_reasons`
- `what_to_wait_for`

This supports a key product requirement: when the system says "do not buy," it must explain the negative decision.

### Replay Confidence Badge

`replay_confidence_badge` separates evidence quality from live signal confidence.

Current validated fixed badge:

- Nasdaq100 conservative proxy track
- `43` trades
- `62.7907%` win rate
- `47.8595%` Wilson lower-bound win rate
- `2.2955` Sharpe
- `-11.4037%` max drawdown
- source artifact: `data/backtests/nasdaq100_conservative_v957_quant_risk_20170120_20260426_proxy.json`

Unknown strategy/universe combinations return `검증 부족` instead of overclaiming.

### Execution Badge

`execution_badge` estimates all-in round-trip cost:

```text
round_trip_cost_pct + spread_bps / 100 + latency_bps / 100
```

Default settings:

- `BACKTEST_ROUND_TRIP_COST_PCT=0.30`
- `SLIPPAGE_BPS_DEFAULT=8.0`
- `EXECUTION_LATENCY_BPS_DEFAULT=5.0`
- `CONSERVATIVE_EXECUTION_COST_LIMIT_PCT=0.55`

Labels:

- `실행 가능`
- `비용 주의`
- `진입 금지`

### Counter-Thesis

`counter_thesis` gives the opposing argument and the conditions that would invalidate the current view. This supports red-team style decision review instead of one-sided AI recommendations.

### Portfolio Impact Map

`portfolio_impact_map` uses available inputs such as:

- `sector_code`
- `market_cap_bucket`
- `beta_spy_60d`
- `beta_qqq_60d`
- `relative_strength_20d`
- `spy_relative_strength_20d`
- `qqq_relative_strength_20d`

It produces a compact exposure note for portfolio-level UI cards.

### Order Draft Preview

`order_draft_preview` is a non-executing draft:

- no broker API call
- whole-share default rounding
- 50/50 split plan for add/reduce/exit
- reference price only

## Inputs Used

The module consumes existing engine fields:

- direction, magnitude, confidence
- strategy decision score and risk flags
- market spread, volume, surprise, relative strength
- weekly Ichimoku cloud bias
- moving average context
- RSI, stochastic, Bollinger-compatible fields
- 0DTE options flow fields
- basic financial statement fields
- QQQ/SPY relative strength and beta fields

## Design Principles

- Deterministic and rule-based
- No additional LLM calls
- No broker execution
- Graceful fallback through the enrichment pipeline
- Additive API contract only
- Evidence badge is separate from recommendation confidence

## Presentation Angle

The main differentiator is not "AI summarizes news." The differentiator is:

> EarningWhisperer explains when not to trade, estimates execution feasibility, shows replay evidence, and gives an opposing thesis before presenting a buy/sell action.
