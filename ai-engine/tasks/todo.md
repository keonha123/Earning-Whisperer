# AI Engine Rebuild Track

## v9.6.2 Structured Equity Research API Track

### Scope Guard
- [x] Rework the equity report API around structured JSON as the primary frontend contract
- [x] Preserve `report_markdown` as a compatibility/rendering fallback
- [x] Keep existing analyze, Redis, and `/v1/engine/*` contracts unchanged
- [x] Ensure Gemini failures or schema failures return deterministic structured fallback data

### Implementation
- [x] Add structured rating box, table, section, thesis, scenario, risk, and source models
- [x] Refactor report service to request JSON from Gemini and validate it with Pydantic
- [x] Derive Markdown from the structured report instead of treating Markdown as the source of truth
- [x] Update API docs and tests

### Validation
- [x] Run targeted equity report tests
- [x] Run full pytest
- [x] Run compile validation

### Review
- Rebuilt the equity report API around `structured_report` as the frontend source of truth.
- Kept `report_markdown` as a derived compatibility/export field.
- Gemini now returns JSON under `application/json`; AI Engine validates with Pydantic before responding.
- Schema failure, empty response, or Gemini failure now return deterministic structured fallback data.
- Validation:
  - `py -3.13 -m pytest tests/test_equity_report_api.py -q` -> `4 passed`
  - `py -3.13 -m pytest tests/test_equity_report_api.py tests/test_legacy_github_compatibility.py tests/test_stats_token_usage.py -q` -> `7 passed`
  - `py -3.13 -m pytest -q` -> `139 passed`
  - `py -3.13 -m compileall .` -> success

## v9.6.1 Equity Research Markdown API Track

### Scope Guard
- [x] Add a quick Markdown report API for frontend rendering
- [x] Keep existing analyze, Redis, and `/v1/engine/*` contracts unchanged
- [x] Use Backend proxy friendly paths: `/v1/research/equity-report` and `/api/v1/research/equity-report`
- [x] Degrade gracefully when Gemini or market-data lookup is unavailable

### Implementation
- [x] Add equity report request/response models
- [x] Add a Gemini-backed Markdown report service
- [x] Add a FastAPI research router
- [x] Add focused API/service tests

### Validation
- [x] Run targeted equity report tests
- [x] Run compile validation

### Review
- Added frontend-ready Markdown report routes:
  - `POST /v1/research/equity-report`
  - `POST /api/v1/research/equity-report`
- Added yfinance snapshot enrichment, Gemini review-route generation, token/cost metadata, sources, data-quality warnings, and fallback Markdown.
- Validation:
  - `py -3.13 -m pytest tests/test_equity_report_api.py tests/test_legacy_github_compatibility.py tests/test_stats_token_usage.py -q` -> `6 passed`
  - `py -3.13 -m pytest -q` -> `138 passed`
  - `py -3.13 -m compileall .` -> success

## v9.5.9 Legacy GitHub Compatibility Track

### Scope Guard
- [x] Keep all non-AI-engine GitHub contracts unchanged
- [x] Preserve existing `/v1/engine/*` and `/analyze` routes
- [x] Add `/api/v1/analyze` as an additive compatibility route
- [x] Publish legacy raw signals to Redis without blocking HTTP analysis on Redis failure

### Implementation
- [x] Add legacy request/response models
- [x] Add legacy-to-v9 request adapter and v9-to-legacy signal adapter
- [x] Add actual Redis signal publisher with graceful degradation
- [x] Wire the legacy router into the existing FastAPI app
- [x] Refresh Gemini default model settings away from deprecated Gemini 3 Pro Preview

### Validation
- [x] Add focused legacy contract tests
- [x] Run targeted compatibility tests
- [x] Run full pytest
- [x] Run compile and dependency checks
- [x] Package a GitHub-ready zip

### Review
- Added `POST /api/v1/analyze` with original payload compatibility.
- Added Redis raw signal publishing for `trading-signals` and enriched publishing for `trading-signals-enriched`.
- Added graceful Redis degradation with publish status fields in the legacy HTTP response.
- Updated Gemini defaults to `gemini-3.1-flash-lite` primary and `gemini-3.1-pro-preview` review.
- Validation: legacy tests `2 passed`; full suite `135 passed`; targeted compile success; `pip check` success.
- Note: `/health/ready` is degraded locally because credentials/database readiness are not configured in this environment.
- Packaged `C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_5_9_legacy_compat_github_ready.zip`.

## v9.5.8 GitHub Packaging Track

### Scope Guard
- [x] Keep source cleanup non-destructive
- [x] Exclude cache, pyc, pytest temp, local env, and generated lock artifacts from the release zip
- [x] Preserve README, CHANGELOG, docs, tests, backtest artifacts, and source modules
- [x] Validate before packaging

### Validation
- [x] Run compile validation
- [x] Run full pytest
- [x] Run dependency compatibility check

### Packaging
- [x] Create clean GitHub staging directory
- [x] Add repository workflow instructions and upload notes
- [x] Zip staging directory
- [x] Verify zip contents

### Review
- Created clean staging directory `C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_5_8_github_ready`.
- Created GitHub-ready zip `C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_5_8_github_ready.zip`.
- Release zip has `212` entries and `0` cache/temp/pyc/env entries.
- Verified README, CHANGELOG, AGENTS, upload notes, decision assistant source, docs, and tests are included.

## v9.5.8 Original GitHub Comparison Documentation Track

### Scope Guard
- [x] Use the GitHub plugin to inspect the original `keonha123/Earning-Whisperer` documentation
- [x] Compare against the current v9.5.8 AI-engine-only package
- [x] Document differences in architecture, APIs, input/output, logic, product goals, and competitive positioning
- [x] Keep the output as a docs artifact, not a code behavior change

### Review
- Added `docs/AI_ENGINE_V3_TO_V958_COMPARISON.md`.
- Updated `CHANGELOG.md` to mention the comparison document.

## v9.5.8 Decision Assistant Product Track

### Scope Guard
- [x] Keep the work inside the AI engine response/enrichment layer
- [x] Preserve existing API contracts with additive-only response fields
- [x] Avoid order execution, frontend implementation, auth, and billing scope
- [x] Keep broad backtest metrics separate from per-signal decision badges

### Implementation
- [x] Add a deterministic `Decision Assistant` core module
- [x] Add sell-first portfolio action guidance
- [x] Add no-trade explainer and blocked-reason chips
- [x] Add replay-confidence and execution-cost badges
- [x] Add counter-thesis output for front cards
- [x] Wire the payload into enrichment, signal brief, and event cards

### Validation
- [x] Add focused unit tests for decision assistant logic
- [x] Add event payload regression coverage
- [x] Run targeted tests and compile validation

### Review
- Added `core/decision_assistant.py` without adding LLM calls or broker execution.
- Added no-trade explanation, replay confidence, execution feasibility, counter-thesis, portfolio impact, and order-draft preview outputs.
- Wired output into `AnalysisEnrichmentPipeline`, `signal_brief`, and productized event cards.
- Validation: `py -3.13 -m compileall core services strategies tools tests -q` -> success.
- Validation: `py -3.13 -m pytest -q` -> `133 passed`.
- Validation: `py -3.13 -m pip check` -> `No broken requirements found.`

## v9.5.7 MIT Quant Bible Integration Track

### Scope Guard
- [x] Use the PDF as a source of quant validation primitives, not as a reason to add unvalidated trading rules
- [x] Keep changes inside the AI-engine research/backtest layer
- [x] Preserve existing API contracts
- [x] Validate with tests and a candidate rerun

### Implementation
- [x] Add Wilson confidence lower-bound helper
- [x] Add beta-binomial Bayesian win-rate helper
- [x] Add bounded fractional Kelly helper
- [x] Add execution edge after spread/latency/uncertainty helper
- [x] Wire Wilson/Bayesian/Kelly diagnostics into backtest metrics
- [x] Add Wilson lower-bound check to promotion evaluation

### Validation
- [x] Extract and review `MIT-Quant-Bible.pdf`
- [x] Add unit tests for quant risk math
- [x] Run targeted tests
- [x] Re-run Nasdaq100 conservative candidate artifact

### Review
- Nasdaq100 conservative remained `prod_candidate`.
- Point-estimate win rate is `62.7907%`; Wilson lower-bound win rate is `47.8595%`.
- Bayesian win-rate mean is `62.2222%`.
- Fractional Kelly diagnostic is `6.0587%`, below the configured max position cap.
- This makes promotion evidence more conservative and less dependent on lucky small-sample point estimates.

## v9.5.6 Operation Readiness Validation Track

### Scope Guard
- [x] Keep validation in the AI-engine research/artifact layer
- [x] Separate proxy, persisted replay, and execution-stress results
- [x] Avoid claiming production readiness without closed replay samples
- [x] Preserve existing API contracts

### Implementation
- [x] Add `--use-database-replay` to the research CLI
- [x] Fix Markdown reports so replay/proxy track notes are visible
- [x] Add execution cost/slippage/latency stress validator
- [x] Add conservative execution-cost blocker at `0.55%` estimated all-in cost
- [x] Emit JSON and Markdown artifacts for replay and execution stress

### Validation
- [x] Confirm local PostgreSQL connectivity
- [x] Run DB-backed replay for Nasdaq100 conservative
- [x] Run execution stress on the v9.5.5 Nasdaq100 conservative candidate
- [x] Add tests for execution stress calculations and report shape

### Review
- DB-backed replay ran successfully but found `0` closed replay samples, so replay promotion is not statistically usable yet.
- Normal broker execution stress passed at `0.55%` all-in cost.
- Earnings-gap stress failed at `0.90%` all-in cost; conservative live/research paths now block entries once estimated all-in execution cost exceeds `0.55%`.
- Validation artifacts were written under `data/backtests/`.

## v9.5.5 Nasdaq100 Conservative Sleeve/Governor Track

### Scope Guard
- [x] Keep the improvement in the AI-engine strategy/research layer
- [x] Preserve existing `/v1/engine/*` contracts
- [x] Keep aggressive tracks research/canary only
- [x] Validate with net returns after costs and timestamp-sorted MDD

### Implementation
- [x] Add constrained Nasdaq100 conservative `REVERSAL_CATALYST` quality sleeve
- [x] Require mega-cap, core sector, and normal regime for the quality sleeve
- [x] Add Nasdaq100 conservative loss-streak and drawdown cooldown governor in the research path
- [x] Keep live and offline approval scope checks aligned through `core/strategy_track_rules.py`

### Validation
- [x] Add tests for quality-sleeve approval/rejection
- [x] Add tests for risk-governor skip behavior
- [x] Run targeted research/strategy tests
- [x] Run full pytest and compile validation
- [x] Re-run 2017-2026 Nasdaq100 conservative and full acceptance matrix

### Review
- Nasdaq100 conservative improved from v9.5.4 MDD `-19.1754%` to `-11.4037%`.
- Win rate improved from `55.8140%` to `62.7907%`.
- Sharpe improved from `1.3244` to `2.2955`.
- Total return improved from `20.7492%` to `31.2770%`.
- Full acceptance matrix selected `nasdaq100_conservative` as the production candidate.
- Validation: `python -m pytest -q` with `122 passed`.

## Scope Guard
- [x] Stay strictly within the AI engine layer
- [x] Preserve existing `/v1/engine/*` contracts with additive-only response changes
- [x] Keep decision + explainability + control as the product center
- [x] Avoid frontend, auth, payment, full gateway, and upstream ingestion scope

## Architecture Reset
- [x] Inventory the current app against `AGENT_PACK/01_Planning_Spec.md`
- [x] Move API handlers out of `main.py` into router modules under `api/`
- [x] Introduce shared app dependencies/container wiring for settings, services, and repositories
- [x] Keep business logic in services/core, not route handlers
- [x] Remove duplicate or unreachable handler logic discovered during migration

## Contract And Product Shape
- [x] Normalize Signal Brief response fields and fallback behavior
- [x] Align README/docs to the AI-engine-only product definition
- [x] Ensure explanation payload stays deterministic and non-empty on blocked decisions
- [x] Keep rollout/calibration/regression/control fields additive and documented

## Persistence And Control Plane
- [x] Verify repository methods remain reachable after router extraction
- [x] Reduce monkey-patched runtime coupling where it blocks maintainability
- [x] Confirm audit, rollout, emergency control, calibration, and regression flows still persist correctly

## Validation
- [x] Run compile validation after restructuring
- [x] Run pytest after restructuring
- [x] Review failures and patch before closing the task

## Review
- Extracted all HTTP handlers from `main.py` into dedicated router modules under `api/routers/`.
- Replaced the old inline runtime overlay block with `services/runtime_dispatch_service.py`.
- Kept `main.create_app`, `main.app`, `main.run_analysis`, and `main._dispatch_analysis` for compatibility with existing tests and consumers.
- Rewrote `README.md` and `docs/SYSTEM_ARCHITECTURE.md` to match the AI-engine-only product definition from the agent pack.
- Validation: `python -m compileall .` and `python -m pytest -q` with `68 passed`.

# v9.4 Strategy Backtest And Validation Track

## Scope Guard
- [x] Keep the work inside the AI engine and offline research CLI/artifact layer only
- [x] Preserve existing `/v1/engine/*` contracts and keep all API changes additive
- [x] Separate proxy backtest results from replay validation results with explicit mode tags
- [x] Keep conservative as the only prod candidate; keep aggressive as research/canary only

## Research Runner
- [x] Add a v9-native `tools/market_interest_backtest.py` runner
- [x] Build deterministic proxy analysis generation for broad-universe research runs
- [x] Reuse current `choose_strategy`, gate thresholds, and hold tuning in the backtest path
- [x] Apply next-session entry, hold-days exits, and net-return cost/slippage handling
- [x] Emit JSON and Markdown artifacts under `data/backtests/`

## Strategy/Profile Alignment
- [x] Remove unsupported strategy references from `core/universe_profiles.py`
- [x] Fix Nasdaq100/SP500 conservative/aggressive strategy sets to match the v9 plan
- [x] Populate `data/universes/` with actual Nasdaq100 and SP500 symbol files
- [x] Add validation so profiles cannot reference strategies the orchestrator never emits

## Metrics And Improvement Loop
- [x] Add full backtest metrics including timestamp-sorted MDD and net win-rate handling
- [x] Add per-universe, per-risk-style, per-strategy, and per-regime breakdowns
- [x] Connect backtest diff output to regression/calibration proposal flows
- [x] Keep aggressive promotion blocked from prod even when research metrics pass

## Token And Cost Telemetry
- [x] Replace the placeholder `core/token_budgeter.py` with operating prompt budget logic
- [x] Standardize Gemini usage metadata with estimated cost, cache hit, and coalescing telemetry
- [x] Expose additive token/cost stats in `/stats`
- [x] Keep broad-universe research runs in proxy mode without live LLM dependency

## Validation
- [x] Add tests for strategy/profile alignment
- [x] Add tests for backtest metrics and execution modes
- [x] Add tests for token/cost telemetry and `/stats`
- [x] Run pytest and targeted acceptance runs after implementation

## Review
- Added a v9-native offline research layer with proxy, replay, and hybrid result blocks.
- Realigned official strategy catalogs so universe/risk-style profiles only reference strategies the orchestrator can actually emit.
- Added prompt-budget and estimated-cost telemetry from the Gemini client up to `GET /stats`.
- Generated live acceptance artifacts under `data/backtests/` using Nasdaq100 and SP500 universe files.
- Acceptance result: no scenario passed production promotion thresholds; `sp500_conservative` is the current conservative candidate but remains non-promotable.

# v9.4 Reference-Aligned Product Upgrade Track

## Scope Guard
- [x] Stay within the AI engine layer while aligning to the presentation deck, integrated report, and agent-pack guidance
- [x] Keep all existing `/v1/engine/*` behavior backward compatible and additive-only
- [x] Avoid frontend, auth, billing, or full data-pipeline implementation

## Product Contract Hardening
- [x] Add a fixed `signal_brief` contract that mirrors the deck/report product definition
- [x] Keep the existing productized event envelope and card outputs intact
- [x] Ensure blocked or neutral decisions still emit non-empty explanation and brief payloads

## Canonical Event Support
- [x] Add optional canonical entity models for company, event, transcript, guidance, and overlays
- [x] Accept canonical bundles as additive request input without breaking legacy analyze requests
- [x] Derive a compact feature-bundle summary from canonical input for prompt and payload usage

## Observability And Source Health
- [x] Add additive source-health/freshness structures for adapters and canonical coverage
- [x] Expose source-health summary in `/stats` and in the persisted envelope
- [x] Persist canonical/source-health snapshots alongside existing feature snapshots

## Validation
- [x] Add focused tests for canonical bundle parsing, signal brief generation, and source-health stats
- [x] Run pytest after implementation
- [x] Run a smoke check for the analysis/event response shape

## Review
- Added additive canonical request models plus a canonical bundle service that emits compact prompt-safe feature bundles.
- Added fixed `signal_brief` payloads at the top level and under `data.signal_brief` without breaking legacy response fields.
- Added source-health telemetry into `/stats` and persistence columns for canonical/source-health/signal-brief snapshots.
- Fixed the prompt-builder/runtime mismatch by making `build_prompt()` accept `route_profile`, `source_type`, and feature-bundle context.
- Validation: targeted compile checks plus `pytest -q` with `78 passed`.

# v9.4 Backtest-Driven Strategy Hardening Track

## Scope Guard
- [x] Keep strategy changes additive and backward compatible for the AI engine contract
- [x] Reuse the same strategy policy path in live analysis and offline backtests
- [x] Fix data-unit mismatches before tuning thresholds
- [x] Validate with full pytest and a 10-year acceptance matrix rerun

## Runtime And Research Fixes
- [x] Normalize `relative_strength_20d` units between proxy backtests and live strategy logic
- [x] Make `AnalyzeRequest.universe_profile` actually affect strategy selection
- [x] Add profile-aware strategy filtering and fallback selection in `choose_strategy()`
- [x] Add continuation hold-floor logic for high-quality profile-approved setups
- [x] Add stricter `trend_up` confirmation checks and SP500-PEAD quality gating
- [x] Connect conservative `risk_off` regime blocking into both live strategy fallback and backtest approval

## Validation
- [x] Add focused tests for profile-aware strategy fallback and RS normalization
- [x] Re-run `pytest -q`
- [x] Re-run 10-year proxy acceptance matrix
- [x] Re-run the same 10-year matrix again to confirm reproducibility

## Review
- Backtest reruns were deterministic: `acceptance_matrix_v94_10y_proxy_final.json` and `acceptance_matrix_v94_10y_proxy_rerun.json` matched exactly on scenario metrics.
- `nasdaq100_conservative` improved from avg trade `-0.1692%` / Sharpe `-0.4052` / MDD `-91.53%` to avg trade `+0.0349%` / Sharpe `+0.0726` / MDD `-76.33%`.
- `sp500_conservative` improved materially on drawdown and expectancy but remains below promotion thresholds.
- Aggressive tracks remain research-only and still fail profitability and drawdown standards.
- Validation: `pytest -q` with `82 passed` and two full 10-year acceptance-matrix reruns completed successfully.

# v9.4 Market Context Expansion Track

## Scope Guard
- [x] Keep all additions additive on `MarketData` and downstream payloads
- [x] Reuse shared feature calculations across live yfinance snapshots and proxy backtests
- [x] Avoid introducing look-ahead leakage into the proxy backtest path
- [x] Keep 0DTE and fundamentals optional so missing data degrades safely

## Feature Expansion
- [x] Add weekly Ichimoku, Bollinger bandwidth, MA200, stochastic, and MA stack context
- [x] Add QQQ/SPY relative-strength and rolling beta context
- [x] Add optional 0DTE options flow overlay fields
- [x] Add additive financial statement quality fields

## Runtime Wiring
- [x] Wire the new context into live yfinance snapshot building
- [x] Wire the same context into proxy backtest feature generation
- [x] Feed the new fields into strategy selection, event quality, signal explanation, and options advice
- [x] Clear broken proxy env variables on yfinance paths for this environment

## Validation
- [x] Add focused tests for higher-timeframe fallback, options overlay, and proxy market-data enrichment
- [x] Run targeted pytest for changed modules
- [x] Run full `pytest -q`
- [x] Run proxy backtest smoke checks after the yfinance proxy fix

## Review
- Added `core/market_feature_utils.py` so live snapshots and proxy backtests share the same RSI, stochastic, Bollinger, ATR, beta, benchmark-relative, and weekly Ichimoku calculations.
- Expanded `MarketData` additively with weekly trend, benchmark-relative, 0DTE, and financial statement fields.
- Updated strategy selection to react to higher-timeframe trend breaks, benchmark underperformance, weak fundamentals, and same-day options flow conflicts.
- Updated options advice to expose a `zero_dte_overlay` instead of blindly recommending same-day structures.
- Validation: `pytest -q` with `85 passed`.
- Proxy smoke artifacts:
  - Conservative: `data/backtests/nasdaq100_feature_context_smoke.json` with `0` approved / `10` rejected signals on `AAPL/MSFT/NVDA`.
  - Aggressive: `data/backtests/nasdaq100_feature_context_smoke_aggressive.json` with `1` approved trade, `+3.2981%` net return, `REVERSAL_CATALYST` on `MSFT`.

# v9.4 Exact-Date Backtest Track

## Scope Guard
- [x] Keep existing `period` backtests working while adding exact calendar-range support
- [x] Reuse the same research service for exact-range proxy and replay runs
- [x] Keep date-range support additive in CLI and report payloads
- [x] Validate with tests before running the long acceptance matrix

## Implementation
- [x] Add `start_date` and `end_date` support to the research CLI
- [x] Thread exact date ranges through proxy history loading and replay sample filtering
- [x] Expose `data_window_label` in reports
- [x] Clean repeated backtest warnings surfaced during the 2020-2025 run

## Validation
- [x] Add exact-range tests
- [x] Run `pytest -q`
- [x] Run the full acceptance matrix for `2020-01-01` to `2025-12-31`

## Review
- Exact-range artifact generated:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy.md`
- Summary:
  - `nasdaq100_conservative`: `145` trades, `48.9655%` win rate, `0.2219%` avg trade, `1.1263` PF, `0.4412` Sharpe, `-40.8479%` MDD, `19.4623%` total return
  - `nasdaq100_aggressive`: `1034` trades, `47.6789%` win rate, `-0.0230%` avg trade, `0.9866` PF, `-0.0615` Sharpe, `-90.5782%` MDD, `-67.4772%` total return
  - `sp500_conservative`: `109` trades, `55.9633%` win rate, `0.2383%` avg trade, `1.2162` PF, `0.9477` Sharpe, `-20.6825%` MDD, `23.5300%` total return
  - `sp500_aggressive`: `3065` trades, `43.2300%` win rate, `-0.4437%` avg trade, `0.7316` PF, `-1.4872` Sharpe, `-100.0%` MDD, `-100.0%` total return
- Selection outcome:
  - best conservative candidate remained `sp500_conservative`
  - no scenario met production promotion thresholds

# v9.4 SP500 Conservative Retune Track

## Scope Guard
- [x] Tune only the AI-engine strategy and research layers
- [x] Keep runtime and research guardrails aligned
- [x] Reuse the same 2020-01-01 to 2025-12-31 acceptance matrix for before/after comparison
- [x] Preserve all API contracts and additive payload behavior

## Implementation
- [x] Analyze `sp500_conservative` loss clusters from the exact-date artifact
- [x] Add shared SP500 conservative sector/composite guardrails for continuation setups
- [x] Prevent utility-sector gap setups from leaking into PEAD fallback
- [x] Extend tests for the new runtime and research guardrails

## Validation
- [x] Run targeted strategy tests
- [x] Run targeted research backtest tests
- [x] Run full `pytest -q`
- [x] Re-run the exact-date acceptance matrix twice during tuning

## Review
- Added `core/strategy_track_rules.py` to centralize SP500 conservative continuation guardrails used by both runtime strategy selection and research backtests.
- Hardened `strategies/orchestrator.py` so SP500 conservative utility-sector continuation setups fall back directly to `SENTIMENT_ONLY` instead of leaking into `PEAD`.
- Hardened `services/research_backtest_service.py` with sector-aware composite floors for SP500 conservative `GAP_AND_GO`.
- Added regression coverage in:
  - `tests/test_strategy_enhancements.py`
  - `tests/test_research_backtest_service.py`
- Validation: `python -m pytest -q` with `89 passed`.
- Final exact-date artifact:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v2.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v2.md`
- Final result:
  - `sp500_conservative`: `51` trades, `58.8235%` win rate, `0.7349%` avg trade, `1.7775` PF, `2.6416` Sharpe, `-10.4207%` MDD, `41.7484%` total return
  - Promotion evaluation: all conservative checks passed, state moved to `prod_candidate`

# v9.4 Nasdaq Conservative Retune Track

## Scope Guard
- [x] Keep changes inside AI-engine strategy selection and research validation
- [x] Keep runtime and backtest guardrails aligned
- [x] Preserve SP500 conservative improvements while tuning Nasdaq100 conservative
- [x] Reuse the same 2020-01-01 to 2025-12-31 exact-date acceptance matrix

## Implementation
- [x] Analyze Nasdaq100 conservative loss clusters and approval leakage
- [x] Add Nasdaq100 conservative overextension guardrails
- [x] Add gap-extension handling that keeps downside-dislocation `NEWS_BREAKOUT` exceptions
- [x] Extend regression tests for the new Nasdaq100 conservative rules

## Validation
- [x] Run targeted strategy tests
- [x] Run targeted research backtest tests
- [x] Run full `pytest -q`
- [x] Re-run the exact-date acceptance matrix through the final v5 artifact

## Review
- Hardened `strategies/orchestrator.py` so Nasdaq100 conservative continuation setups fall back to `SENTIMENT_ONLY` when the tape is overheated (`overextended_rsi` / `stacked_overbought`).
- Refined the gap-extension rule so conservative Nasdaq `NEWS_BREAKOUT` can still trade large downside dislocations, while oversized upside chase setups remain blocked.
- Hardened `services/research_backtest_service.py` with matching Nasdaq100 conservative approval rules so research and runtime stay aligned.
- Added regression coverage for:
  - conservative Nasdaq overextension blocking
  - negative-gap `NEWS_BREAKOUT` exception handling
  - backtest approval behavior
- Validation: `python -m pytest -q` with `93 passed`.
- Final exact-date artifact:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v5.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v5.md`
- Final result:
  - `nasdaq100_conservative`: `40` trades, `57.5%` win rate, `0.6346%` avg trade, `1.5052` PF, `1.5914` Sharpe, `-9.9275%` MDD, `25.4886%` total return
  - `sp500_conservative`: `51` trades, `58.8235%` win rate, `0.7349%` avg trade, `1.7775` PF, `2.6416` Sharpe, `-10.4207%` MDD, `41.7484%` total return
  - both conservative tracks now pass production thresholds and evaluate as `prod_candidate`

# v9.4 Aggressive Redesign Track

## Scope Guard
- [x] Keep changes inside AI-engine strategy selection and research validation only
- [x] Preserve conservative-track behavior while redesigning aggressive tracks
- [x] Treat aggressive as a research/canary track, not a production candidate
- [x] Prefer event-quality narrowing over threshold relaxation

## Implementation
- [x] Reconstruct aggressive loss clusters from the final exact-date artifact
- [x] Add shared aggressive track rules for Nasdaq100 and SP500
- [x] Align runtime strategy selection with research approval blocking
- [x] Extend tests for the new aggressive rules

## Validation
- [x] Run targeted strategy tests
- [x] Run targeted research backtest tests
- [x] Run full `pytest -q`
- [x] Re-run the exact-date acceptance matrix for `2020-01-01` to `2025-12-31`

## Review
- Artifact analysis showed the prior aggressive design was still effectively a threshold-relaxation layer.
- Current redesign target:
  - `NASDAQ100 aggressive`: keep only selected `REVERSAL_CATALYST` participation, block `high_vol` / `risk_off`, and exclude the worst reversal sectors.
  - `SP500 aggressive`: keep only selected `PEAD` participation, block `high_vol`, and exclude the worst PEAD sectors.
- Added shared aggressive research-track rules in `core/strategy_track_rules.py` and aligned runtime/backtest blocking in:
- Added shared aggressive research-track rules in `core/strategy_track_rules.py` and aligned runtime/backtest blocking in:
  - `strategies/orchestrator.py`
  - `services/research_backtest_service.py`
- Refined Nasdaq aggressive further by allowing non-reversal candidate rotation only inside selected reversal-rotation sectors:
  - `COMMUNICATION_SERVICES`
  - `CONSUMER_DEFENSIVE`
  - `BASIC_MATERIALS`
- Added regression coverage in:
  - `tests/test_strategy_enhancements.py`
  - `tests/test_research_backtest_service.py`
- Validation:
  - targeted tests passed
  - full `python -m pytest -q` passed with `100 passed`
- Final exact-date artifact:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v7.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v7.md`
- Final result:
  - `nasdaq100_aggressive`: `60` trades, `71.6667%` win rate, `0.7885%` avg trade, `2.1743` PF, `3.7544` Sharpe, `-9.4087%` MDD, `57.1358%` total return
  - `sp500_aggressive`: `62` trades, `62.9032%` win rate, `1.1112%` avg trade, `2.0738` PF, `2.5019` Sharpe, `-13.8193%` MDD, `91.1128%` total return
- Outcome:
  - `sp500_aggressive` now passes all aggressive research thresholds but remains `research_canary_only` by design
  - `nasdaq100_aggressive` now also passes the aggressive research sample floor while remaining `research_canary_only` by design

# v9.4 Full Verification And Hardening Track

## Scope Guard
- [x] Keep work inside the AI engine and offline research layer only
- [x] Preserve public contracts and additive payload behavior
- [x] Focus on runtime stability, structural correctness, and research/runtime alignment
- [x] Avoid speculative refactors that do not improve execution safety or maintainability

## Verification
- [x] Run full test suite
- [x] Run compile/import validation
- [x] Re-check latest backtest artifacts and report consistency
- [x] Inspect critical runtime and research paths for latent bugs

## Fixes
- [x] Patch any contract, control-flow, or research/runtime drift issues found during review
- [x] Patch any validation or compatibility failures
- [x] Apply only targeted optimizations that materially improve maintainability or execution safety

## Review
- Fixed a structural runtime wiring bug in [main.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\main.py): `/v1/engine/analyze` now uses the app-scoped `AnalysisService` instead of recreating a fresh service through `run_analysis()` on every request.
- Fixed per-app isolation in [main.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\main.py): `create_app()` now captures its own FastAPI app in the dispatch closure, so test and multi-instance app state no longer bleed through the module-global `app`.
- Fixed `/stats` semantics in [api/routers/health.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\api\routers\health.py): route-profile counts now come from token telemetry, while model-level routing is exposed separately as `llm_route_counts`.
- Fixed LLM response hard-failure risk in [core/analysis_service.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\analysis_service.py): invalid JSON or schema drift now degrades to a neutral analysis with `metadata.llm_error` instead of raising.
- Fixed external readiness semantics in [api/routers/health.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\api\routers\health.py): `/health/ready` now reports missing `GEMINI_API_KEY` and database dependency failures through additive `checks`.
- Fixed degraded-environment latency in [db/postgres_executor.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\db\postgres_executor.py): PostgreSQL connections now use a 2-second connect timeout plus a 15-second fast-fail cooldown after a failed connection attempt.
- Fixed broken dependency messaging in [db/postgres_executor.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\db\postgres_executor.py): PostgreSQL driver errors are now readable and actionable.
- Added environment bootstrap artifacts:
  - [requirements.txt](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\requirements.txt)
  - updated [README.md](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\README.md)
  - updated [.env.example](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\.env.example)
- Added regression coverage in:
  - [tests/test_runtime_dispatch_paths.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_runtime_dispatch_paths.py)
  - [tests/test_stats_token_usage.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_stats_token_usage.py)
  - [tests/test_analysis_service_fallback.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_analysis_service_fallback.py)
  - [tests/test_health_ready.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_health_ready.py)
  - [tests/test_postgres_executor.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_postgres_executor.py)
  - [tests/test_main_productized_response.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_main_productized_response.py)
  - [tests/test_control_plane_api.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_control_plane_api.py)
  - [tests/test_main_persistence_api.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_main_persistence_api.py)
- Validation:
  - `python -m pytest -q` -> `107 passed`
  - `python -m compileall .` -> success, with only harmless temp-directory listing warnings for `.pytest_tmp`
- FastAPI smoke on a fresh `create_app()` instance -> `/v1/engine/analyze` returned `200`, `/stats` showed `route_counts={'economy': 1}` and `llm_route_counts={'gemini-3.1-flash-preview': 1}`
  - External readiness smoke on the current machine:
    - first `/health/ready` call degraded in `4.251s`
    - second `/health/ready` call degraded in `0.004s` because PostgreSQL fast-fail cooldown engaged
    - `/v1/engine/analyze` completed in `0.015s` after the DB failure cooldown engaged

# v9.4 Live Persistence Bootstrap Fix Track

## Scope Guard
- [x] Keep the public persistence API contract unchanged
- [x] Fix the schema/repository mismatch at the bootstrap layer instead of weakening repository writes
- [x] Make the schema migration idempotent for already-bootstrapped PostgreSQL databases
- [x] Validate with both unit tests and a real local PostgreSQL persist smoke

## Implementation
- [x] Add an idempotent replay-track uniqueness migration to `sql/ai_engine_event_store_schema.sql`
- [x] Preserve single-row-per-run replay semantics for `ai_replay_tracks`
- [x] Add regression coverage so `ON CONFLICT (run_id)` stays backed by schema uniqueness

## Validation
- [x] Re-run targeted persistence/schema tests
- [x] Re-run the real `analyze-and-persist` path against the local PostgreSQL instance
- [x] Re-check `/v1/engine/runs` and run-bundle retrieval after persistence succeeds

## Review
- Fixed the schema/repository contract drift in [sql/ai_engine_event_store_schema.sql](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\sql\ai_engine_event_store_schema.sql): `ai_replay_tracks` now performs a bootstrap-time deduplication pass and then adds the missing `ai_replay_tracks_run_id_key` unique constraint.
- Kept the repository write contract intact in [repositories/event_store_repository.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\repositories\event_store_repository.py): replay persistence remains a single-row-per-run upsert using `ON CONFLICT (run_id)`.
- Added regression coverage in [tests/test_event_store_repository.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_event_store_repository.py) so the replay upsert and the schema constraint/migration stay aligned.
- Validation:
  - `python -m pytest tests/test_event_store_repository.py -q` -> `15 passed`
  - `python -m pytest -q` -> `108 passed`
  - Real local PostgreSQL smoke:
    - `POST /v1/engine/admin/bootstrap-schema` -> `200`
    - `POST /v1/engine/analyze-and-persist` -> `200`
    - `GET /v1/engine/runs` returned the persisted run
    - `GET /v1/engine/runs/{run_id}` returned the stored bundle
  - PostgreSQL invariant check:
    - `ai_replay_tracks_run_id_key` exists
    - duplicate `run_id` count in `ai_replay_tracks` = `0`

# v9.5 Institutional Differentiation Track

## Scope Guard
- [x] Keep existing analyze and persistence contracts additive-only
- [x] Add institution-grade differentiation without live LLM cost or new external dependencies
- [x] Prefer deterministic evidence, execution, capacity, and red-team checks over marketing copy
- [x] Preserve current strategy, rollout, and replay behavior

## Implementation
- [x] Add an institutional edge scoring module
- [x] Attach the edge package to analysis metadata, product surface, signal brief, and cards
- [x] Include capacity/slippage, evidence quality, approval state, red-team thesis, and kill conditions
- [x] Document how this differs from retail brokerage AI summaries

## Validation
- [x] Add focused unit tests for the institutional edge package
- [x] Add response-shape tests for analyze payload exposure
- [x] Run targeted and full regression tests
- [x] Package the updated project zip

## Review
- Added [institutional_edge.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\institutional_edge.py), a deterministic institutional-readiness package with evidence, execution, risk, edge distinctiveness, capacity, and red-team checks.
- Wired institutional edge output into:
  - [analysis_service.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\analysis_service.py)
  - [event_payload_builder.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\event_payload_builder.py)
  - [signal_brief.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\signal_brief.py)
- Added regression coverage in:
  - [test_institutional_edge.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_institutional_edge.py)
  - [test_institutional_edge_response.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_institutional_edge_response.py)
  - [test_analysis_service_fallback.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\tests\test_analysis_service_fallback.py)
- Validation:
  - targeted institutional tests -> `4 passed`
  - `python -m pytest -q` -> `111 passed`
  - `python -m compileall .` -> success, with only existing temp-directory listing warnings
  - FastAPI smoke confirmed `metadata.institutional_edge`, `data.analysis.institutional_edge`, and `institutional_edge` card exposure
- Packaged artifact:
  - [EarningWhisperer_v9_5_0_institutional_edge_ready.zip](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_5_0_institutional_edge_ready.zip)
  - `172` entries
  - `8,572,180` bytes

# v9.5 Architecture Harmonization Track

## Scope Guard
- [x] Keep all public API contracts unchanged
- [x] Avoid broad rewrites outside the live analysis path
- [x] Separate model orchestration from deterministic enrichment
- [x] Preserve strategy, control, replay, and persistence behavior

## Implementation
- [x] Introduce `AnalysisEnrichmentPipeline`
- [x] Move strategy, trade plan, options, explanation, product surface, and institutional edge assembly behind the enrichment boundary
- [x] Keep `AnalysisService` focused on feature bundle, routing, prompt/model call, fallback, and telemetry
- [x] Document the selected architecture, design patterns, and algorithms

## Validation
- [x] Add enrichment pipeline regression coverage
- [x] Run targeted architecture tests
- [x] Run full regression suite
- [x] Package the updated project zip

## Review
- Added [analysis_enrichment.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\analysis_enrichment.py) as the deterministic post-LLM enrichment boundary.
- Reduced `AnalysisService` coupling so [analysis_service.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\analysis_service.py) now focuses on context, phase-1 scoring, routing, prompt/model call, fallback, and token telemetry.
- Kept strategy selection, trade plan, options advice, explanation, product surface, and institutional edge behind `AnalysisEnrichmentPipeline`.
- Added [ARCHITECTURE_AND_ALGORITHMS.md](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\docs\ARCHITECTURE_AND_ALGORITHMS.md) and updated [SYSTEM_ARCHITECTURE.md](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\docs\SYSTEM_ARCHITECTURE.md).
- Validation:
  - targeted architecture tests -> `5 passed`
  - `python -m pytest -q` -> `112 passed`
  - `python -m compileall .` -> success, with only existing temp-directory listing warnings
  - FastAPI smoke confirmed `product_surface`, `institutional_edge`, and `institutional_edge` card exposure
- Packaged artifact:
  - [EarningWhisperer_v9_5_1_architecture_harmonized_ready.zip](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_5_1_architecture_harmonized_ready.zip)
  - initial size before final task-log update: `8,577,324` bytes

# v9.5 Signal DataHub Reimplementation Track

## Scope Guard
- [x] Reimplement useful external-reference concepts without copying AGPL/commercial-licensed code
- [x] Keep the project direction centered on AI-engine decision, explainability, control, and institutional readiness
- [x] Preserve all existing `/v1/engine/*` and `/stats` response fields with additive-only output
- [x] Avoid adding frontend, broker execution, upstream ingestion, or new external dependencies

## Implementation
- [x] Add a Python-native `SignalDataHub` for topic-based runtime data sharing
- [x] Include TTL freshness, stale handling, source/domain statistics, and in-flight producer dedupe counters
- [x] Wire canonical feature bundles and source-health summaries into the data hub during analysis
- [x] Expose additive data-hub health and cache-efficiency metrics through `/stats`

## Validation
- [x] Add unit tests for data-hub cache, stale, source-health, and coalescing behavior
- [x] Add `/stats` regression coverage for data-hub metrics
- [x] Run targeted tests, full pytest, compile validation, and FastAPI smoke checks
- [x] Package the updated project zip

## Review
- Added [signal_data_hub.py](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\core\signal_data_hub.py), an in-process topic hub for feature bundles and source-health snapshots.
- Wired `AnalysisService` so every analysis records `feature_bundle:{ticker}` and `source_health:{source}` topics without changing existing analyze inputs.
- Exposed additive runtime observability through `/stats`:
  - `signal_data_hub`
  - `datahub_topic_count`
  - `datahub_cache_hit_rate`
  - `datahub_stale_topic_rate`
  - `datahub_coalesced_hit_rate`
- Added response exposure under `data.analysis.signal_data_hub` and metadata receipt under `metadata.signal_data_hub`.
- Validation:
  - `python -m pytest tests/test_event_payload_builder.py tests/test_signal_data_hub.py tests/test_stats_token_usage.py tests/test_analysis_service_fallback.py -q` -> `7 passed`
  - `python -m pytest -q` -> `116 passed`
  - `python -m compileall .` -> success, with only existing temp-directory listing warnings
  - FastAPI smoke confirmed analyze and stats data-hub fields
- Packaged artifact:
  - [EarningWhisperer_v9_5_2_signal_data_hub_ready.zip](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_5_2_signal_data_hub_ready.zip)
  - `169` entries
  - final size recorded by the packaging command

# v9.5 Long-Window Compatibility And Backtest Track

## Scope Guard
- [x] Use the exact requested window: `2017-01-20` through `2026-04-26`
- [x] Use Nasdaq100 and SP500 universe files already maintained by the AI engine
- [x] Keep the run in `price_proxy` mode and do not mix it with replay-ground results
- [x] Preserve existing HTTP/API contracts

## Implementation
- [x] Run dependency and runtime compatibility checks
- [x] Fix yfinance batch-download exit stability for Windows/Python 3.13
- [x] Align `requirements.txt` with the validated current runtime
- [x] Expand acceptance markdown output with total return, benchmark, and recommended state
- [x] Add a dedicated long-window backtest review document

## Validation
- [x] Run 2017-2026 Nasdaq100/SP500 acceptance matrix
- [x] Re-run the same matrix after the yfinance exit-stability patch
- [x] Compare scenario metrics between the first artifact and rerun
- [x] Run targeted tests and full regression suite

## Review
- Backtest artifacts:
  - [acceptance_matrix_v952_20170120_20260426_proxy_rerun.json](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\data\backtests\acceptance_matrix_v952_20170120_20260426_proxy_rerun.json)
  - [acceptance_matrix_v952_20170120_20260426_proxy_rerun.md](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\data\backtests\acceptance_matrix_v952_20170120_20260426_proxy_rerun.md)
  - [BACKTEST_2017_2026_REVIEW.md](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_3_3_ai_engine_auto_promotion_api\ewproj\ai_engine\docs\BACKTEST_2017_2026_REVIEW.md)
- Selected production candidate remained `sp500_conservative`, but no scenario met production promotion criteria.
- `nasdaq100_aggressive` passed aggressive research thresholds but remains `research_canary_only` by policy.
- Validation:
  - `python -m pip check` -> `No broken requirements found.`
  - `python -m pytest tests/test_research_backtest_service.py tests/test_signal_data_hub.py tests/test_stats_token_usage.py tests/test_event_payload_builder.py -q` -> `18 passed`
  - `python -m pytest -q` -> `117 passed`
  - `python -m compileall .` -> success, with only existing temp-directory listing warnings
- Packaged artifact:
  - [EarningWhisperer_v9_5_3_compat_backtest_ready.zip](C:\Users\james\source\repos\files2_work\EarningWhisperer_v9_5_3_compat_backtest_ready.zip)
  - `174` entries
  - final size recorded by the packaging command

# v9.5 Nasdaq100 Conservative Retune Track

## Scope Guard
- [x] Improve Nasdaq100 conservative by removing loss pockets, not by relaxing thresholds
- [x] Keep aggressive track policy unchanged
- [x] Keep SP500 conservative/aggressive behavior unchanged
- [x] Wire rules into both live strategy selection and offline research approval

## Implementation
- [x] Add Nasdaq100 conservative core-sector rule
- [x] Add Nasdaq100 conservative high-volatility NEWS_BREAKOUT blocker
- [x] Add shared helper functions in `core/strategy_track_rules.py`
- [x] Add targeted unit tests for research approval and live orchestrator behavior

## Validation
- [x] Run targeted strategy/research tests
- [x] Run Nasdaq100 conservative 2017-2026 rerun
- [x] Run full Nasdaq100/SP500 acceptance matrix rerun
- [x] Run full regression suite and compile validation

## Review
- Nasdaq100 conservative improved:
  - trades: `70 -> 43`
  - win rate: `48.5714% -> 55.8140%`
  - average trade: `0.1008% -> 0.4981%`
  - median trade: `-0.4710% -> 1.0808%`
  - profit factor: `1.0654 -> 1.3936`
  - Sharpe: `0.2533 -> 1.3244`
  - MDD: `-29.5416% -> -19.1754%`
  - total return: `2.4619% -> 20.7492%`
- Full matrix confirmed no changes to Nasdaq100 aggressive or SP500 tracks.
- `nasdaq100_conservative` became the selected conservative candidate, but production promotion remains blocked by MDD threshold.
- Validation:
  - `python -m pytest -q` -> `120 passed`
  - `python -m compileall .` -> success, with only existing temp-directory listing warnings
  - `python -m pip check` -> `No broken requirements found.`
