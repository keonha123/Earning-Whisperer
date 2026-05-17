# Changelog

## v9.6.2 - 2026-05-17

### Changed

- Reworked equity research reports around validated `structured_report` JSON as the frontend source of truth.
- Kept `report_markdown` as a derived compatibility/export field.
- Changed `EquityReportRequest.output_format` default from `markdown` to `structured`, while still accepting `markdown`.
- Gemini report generation now requests `application/json` and validates the payload with Pydantic before returning it.

### Added

- Added structured report models:
  - `ResearchRatingBox`
  - `ResearchTable`
  - `ResearchSection`
  - `ResearchScenario`
  - `StructuredEquityReport`
- Added schema-failure fallback so invalid LLM output returns deterministic structured data instead of breaking the API.

### Compatibility

- Existing analyze, Redis publishing, `/v1/engine/*`, control, calibration, regression, and stats contracts remain unchanged.
- Existing report clients can still render `report_markdown`, but new frontend work should render `structured_report`.

## v9.6.1 - 2026-05-17

### Added

- Added frontend-ready equity research report API:
  - `POST /v1/research/equity-report`
  - `POST /api/v1/research/equity-report`
- Added `models/equity_report_models.py` for report request/response contracts.
- Added `services/equity_report_service.py` with yfinance snapshot enrichment, Gemini report generation, token/cost metadata, and conservative fallback output.
- Added `api/routers/equity_research.py`.
- Added `docs/EQUITY_RESEARCH_REPORT_API.md`.
- Added focused API and fallback tests in `tests/test_equity_report_api.py`.

### Compatibility

- Existing analyze, Redis publishing, `/v1/engine/*`, control, calibration, regression, and stats contracts remain unchanged.
- The new `/api/v1/research/equity-report` path is intended for Backend proxy integration with the original GitHub frontend stack.

## v9.5.9 - 2026-05-13

### Added

- Added `POST /api/v1/analyze` for compatibility with the original `keonha123/Earning-Whisperer` data pipeline.
- Added `models/legacy_contract_models.py` with legacy analyze request, raw signal response, and publish result contracts.
- Added `services/legacy_contract_adapter.py` to map legacy payloads into v9 `AnalyzeRequest` objects and v9 envelopes back into raw Redis signals.
- Added `services/redis_signal_publisher.py` for Redis `trading-signals` and `trading-signals-enriched` publishing with backup queue and graceful degradation.
- Added legacy compatibility tests for request mapping, Redis payload shape, and Redis failure behavior.
- Added `docs/LEGACY_GITHUB_COMPATIBILITY_SPEC.md`.
- Added `docs/AI_ENGINE_INPUT_OUTPUT_DELTA.md`.

### Changed

- Updated default Gemini fast/primary model to `gemini-3.1-flash-lite`.
- Kept review/escalation model as `gemini-3.1-pro-preview`.
- Removed deprecated `gemini-3-pro-preview` from default candidate routing.
- Added Redis publish feature flags and socket timeout settings to `.env.example`.
- Preserved original timestamps and sequence numbers under `request_metadata` in v9 response envelopes.

### Compatibility

- Existing `/v1/engine/analyze`, `/analyze`, `/v1/engine/events/persist`, and `/v1/engine/analyze-and-persist` routes remain unchanged.
- Original Backend consumers can continue reading required raw fields from Redis channel `trading-signals`.

## v9.5.8 - 2026-05-03

### Added

- Added `core/decision_assistant.py`, a deterministic product layer for buy/sell judgment.
- Added `docs/AI_ENGINE_V3_TO_V958_COMPARISON.md` comparing the original GitHub v3.5.2 AI engine with the current v9.5.8 AI engine.
- Added advisory-only sell-first guidance:
  - `ADD`
  - `HOLD`
  - `REDUCE`
  - `EXIT`
  - `AVOID`
- Added no-trade explainer payload with Korean deny summary, blocked reasons, and wait-for conditions.
- Added replay confidence badge using the validated Nasdaq100 conservative proxy artifact.
- Added execution badge using spread, round-trip cost, and latency cost against the conservative execution limit.
- Added counter-thesis, portfolio impact map, order draft preview, and frontend-ready driver/risk chips.
- Added `decision_assistant` card output in the productized event envelope.
- Added `docs/DECISION_ASSISTANT_PRODUCT_LAYER.md`.
- Added tests for decision assistant logic and event payload integration.

### Changed

- `AnalysisEnrichmentPipeline` now attaches decision assistant output to:
  - `metadata.decision_assistant`
  - `metadata.product_surface.decision_assistant`
  - `front_payload_ko.decision_assistant`
  - `frontend_contract_ko.decision_assistant`
- `signal_brief` now includes optional decision assistant fields:
  - `sell_first_action`
  - `recommended_change_pct`
  - `position_intent_ko`
  - `no_trade_summary_ko`
  - `replay_confidence_badge`
  - `execution_badge`
  - `counter_thesis_ko`

### Validation

- Targeted tests: `py -3.13 -m pytest tests/test_decision_assistant.py tests/test_event_payload_builder.py tests/test_analysis_enrichment_pipeline.py -q` -> `5 passed`

## v9.5.7 - 2026-05-03

### Added

- Added `core/quant_risk_math.py` with:
  - Wilson lower confidence bound
  - beta-binomial Bayesian win-rate mean
  - bounded fractional Kelly sizing
  - execution edge after spread/latency/uncertainty cost
- Added backtest metrics:
  - `wilson_win_rate_lower_pct`
  - `bayesian_win_rate_mean_pct`
  - `fractional_kelly_pct`
- Added `docs/MIT_QUANT_BIBLE_APPLICATION.md`.
- Added tests for the new quant risk math primitives.

### Changed

- Promotion evaluation now requires a Wilson win-rate lower-bound check in addition to point-estimate win rate.
- Backtest Markdown reports now show Wilson lower bound, Bayesian win-rate mean, and fractional Kelly diagnostics.

### Validation

- PDF reference reviewed: probability, confidence interval, Kelly sizing, regression discipline, and market-making execution-risk concepts were selected as applicable.
- Nasdaq100 conservative quant-risk rerun:
  - `43` trades
  - `62.7907%` win rate
  - `47.8595%` Wilson win-rate lower bound
  - `62.2222%` Bayesian win-rate mean
  - `6.0587%` fractional Kelly diagnostic
  - `0.6808%` average trade
  - `2.2955` Sharpe
  - `-11.4037%` MDD
  - `prod_candidate`
- Targeted tests: `python -m pytest tests/test_quant_risk_math.py tests/test_research_backtest_service.py tests/test_execution_stress_validate.py -q` -> `22 passed`
- Full local test suite: `python -m pytest -q` -> `130 passed`
- Compile validation: `python -m compileall services core strategies tools tests -q` -> success
- Dependency validation: `python -m pip check` -> `No broken requirements found.`

## v9.5.6 - 2026-04-27

### Added

- Added DB-backed replay execution support to `tools/market_interest_backtest.py` via `--use-database-replay`.
- Added `tools/execution_stress_validate.py` for broker cost, spread, and latency stress validation on backtest artifacts.
- Added conservative live/research execution-cost blocking when estimated all-in cost exceeds `0.55%`.
- Added `docs/OPERATION_READINESS_VALIDATION.md`.
- Added tests for the execution stress validator.

### Fixed

- Backtest Markdown reports now include notes from the effective replay/proxy track, not only top-level run notes.

### Validation

- DB replay command completed with PostgreSQL available, but current database has `0` closed replay samples for the requested Nasdaq100 universe.
- Execution stress validation on Nasdaq100 conservative:
  - base recomputed `0.38%` all-in cost: passed
  - broker normal `0.55%` all-in cost: passed
  - earnings gap stress `0.90%` all-in cost: failed
  - extreme spread stress `1.40%` all-in cost: failed
- Nasdaq100 conservative proxy rerun after execution-cost blocker remained unchanged:
  - `43` trades, `62.7907%` win rate, `0.6808%` average trade, `2.2955` Sharpe, `-11.4037%` MDD
- Targeted tests: `python -m pytest tests/test_strategy_enhancements.py tests/test_research_backtest_service.py tests/test_execution_stress_validate.py -q` -> `36 passed`
- Full local test suite: `python -m pytest -q` -> `126 passed`
- Compile validation: `python -m compileall services core strategies tools tests -q` -> success
- Dependency validation: `python -m pip check` -> `No broken requirements found.`

## v9.5.5 - 2026-04-27

### Added

- Added a Nasdaq100 conservative quality-reversal sleeve:
  - `REVERSAL_CATALYST` is allowed only for mega-cap `TECHNOLOGY` / `COMMUNICATION_SERVICES` events in `normal` regime.
  - Non-scope reversal setups are blocked with `nasdaq_conservative_quality_reversal_scope`.
- Added a Nasdaq100 conservative research risk governor:
  - skips the next candidate after `2` consecutive net losing trades
  - pauses candidates for `30` days after an `-8%` realized track drawdown trigger
- Added `docs/NASDAQ100_CONSERVATIVE_SLEEVE_GOVERNOR.md`.

### Changed

- Updated the Nasdaq100 conservative official strategy catalog to include the constrained `REVERSAL_CATALYST` sleeve.
- Kept the sleeve and risk rules shared between live selection and offline approval paths where applicable.

### Validation

- Targeted research/strategy tests: `python -m pytest tests/test_research_backtest_service.py tests/test_strategy_enhancements.py -q` -> `32 passed`
- Full local test suite: `python -m pytest -q` -> `122 passed`
- Compile validation: `python -m compileall services core strategies tests -q` -> success
- Nasdaq100 conservative rerun:
  - trade count `43`
  - win rate `62.7907%`
  - average trade `0.6808%`
  - median trade `1.2479%`
  - profit factor `1.6782`
  - Sharpe `2.2955`
  - MDD `-11.4037%`
  - total return `31.2770%`
  - production state `prod_candidate`
- Full 2017-2026 acceptance matrix selected `nasdaq100_conservative` as the production candidate.

## v9.5.4 - 2026-04-26

### Fixed

- Retuned Nasdaq100 conservative approval logic after the 2017-2026 backtest showed weak expectancy from non-core sectors and high-volatility news breakouts.
- Added `nasdaq_conservative_non_core_sector` and `nasdaq_conservative_high_vol_news_breakout` blockers.
- Kept missing sector metadata graceful: unknown sector does not block live analysis by itself.

### Changed

- Wired the new blockers into both:
  - live strategy selection in `strategies/orchestrator.py`
  - offline proxy/replay approval in `services/research_backtest_service.py`
- Added shared helper functions and constants in `core/strategy_track_rules.py`.

### Added

- Added `docs/NASDAQ100_CONSERVATIVE_RETUNE.md` with before/after performance attribution.
- Added unit coverage for the new Nasdaq100 conservative blockers.

### Validation

- Targeted strategy/research tests: `python -m pytest tests/test_research_backtest_service.py tests/test_strategy_enhancements.py -q` -> `30 passed`
- Nasdaq100 conservative rerun:
  - trade count `70 -> 43`
  - win rate `48.5714% -> 55.8140%`
  - average trade `0.1008% -> 0.4981%`
  - median trade `-0.4710% -> 1.0808%`
  - profit factor `1.0654 -> 1.3936`
  - Sharpe `0.2533 -> 1.3244`
  - MDD `-29.5416% -> -19.1754%`
  - total return `2.4619% -> 20.7492%`
- Full acceptance matrix rerun completed normally:
  - selected production candidate became `nasdaq100_conservative`
  - no production promotion yet because conservative MDD still exceeds the `-12%` limit
- Full local test suite: `python -m pytest -q` -> `120 passed`
- Compile/import validation: `python -m compileall .` -> success, with only existing temp-directory listing warnings
- Dependency check: `python -m pip check` -> `No broken requirements found.`

## v9.5.3 - 2026-04-26

### Fixed

- Fixed long-running research CLI exit stability on Windows/Python 3.13 by disabling yfinance worker threads in batch downloads.
- Reconciled `requirements.txt` with the current validated runtime:
  - Python 3.13.7
  - FastAPI 0.135.3
  - Pydantic 2.12.5
  - Pandas 2.3.3
  - NumPy 2.2.6
  - yfinance 1.2.0
  - google-genai 1.70.0

### Changed

- Expanded acceptance-matrix Markdown reports with total return, benchmark return, and recommended state columns.

### Added

- Added `docs/BACKTEST_2017_2026_REVIEW.md` summarizing the Trump first-term start through current-date Nasdaq100/SP500 proxy backtest.
- Added regression coverage for the expanded acceptance markdown contract.

### Validation

- Dependency check: `python -m pip check` -> `No broken requirements found.`
- Long-window acceptance rerun:
  - `2017-01-20` to `2026-04-26`
  - Nasdaq100 and SP500 universe files
  - `price_proxy` mode
  - rerun completed normally
  - scenario metrics matched the prior artifact exactly
- Targeted research/datahub/API tests: `python -m pytest tests/test_research_backtest_service.py tests/test_signal_data_hub.py tests/test_stats_token_usage.py tests/test_event_payload_builder.py -q` -> `18 passed`
- Full local test suite: `python -m pytest -q` -> `117 passed`
- Compile/import validation: `python -m compileall .` -> success, with only existing temp-directory listing warnings

## v9.5.2 - 2026-04-26

### Added

- Added `core/signal_data_hub.py`, a Python-native runtime data hub that reimplements useful terminal-style producer/connector concepts without copying external licensed code.
- Added topic-based records for:
  - `feature_bundle:{ticker}`
  - `source_health:{source}`
- Added TTL freshness, stale handling, cache hit/miss metrics, producer call/error metrics, and in-flight coalescing counters.
- Added additive analysis metadata under `metadata.signal_data_hub`.
- Added additive `/stats` fields:
  - `signal_data_hub`
  - `datahub_topic_count`
  - `datahub_cache_hit_rate`
  - `datahub_stale_topic_rate`
  - `datahub_coalesced_hit_rate`

### Changed

- Wired `AnalysisService` so every analysis records canonical feature-bundle and source-health summaries into `SignalDataHub`.
- Updated README and architecture docs to describe the data-hub boundary.

### Validation

- Targeted data-hub/API tests: `python -m pytest tests/test_event_payload_builder.py tests/test_signal_data_hub.py tests/test_stats_token_usage.py tests/test_analysis_service_fallback.py -q` -> `7 passed`
- Full local test suite: `python -m pytest -q` -> `116 passed`
- Compile/import validation: `python -m compileall .` -> success, with only existing temp-directory listing warnings
- FastAPI smoke:
  - `POST /v1/engine/analyze` -> `200`
  - `data.analysis.signal_data_hub` present
  - `GET /stats` -> `200`
  - `signal_data_hub.by_domain.source_health` present

## v9.5.1 - 2026-04-26

### Changed

- Refactored post-LLM deterministic processing into `core/analysis_enrichment.py`.
- Slimmed `core/analysis_service.py` so it focuses on:
  - canonical feature bundle construction
  - phase-1 scoring
  - route selection
  - prompt/model call
  - response parsing and fallback
  - token telemetry
- Moved strategy selection, trade plan, options advice, signal explanation, product surface, and institutional edge attachment behind `AnalysisEnrichmentPipeline`.

### Added

- Added `tests/test_analysis_enrichment_pipeline.py` to lock the new enrichment boundary.
- Added `docs/ARCHITECTURE_AND_ALGORITHMS.md` with the selected design patterns, algorithms, and module boundaries.
- Updated `docs/SYSTEM_ARCHITECTURE.md` and `README.md` to reflect the pipeline/facade architecture.

### Validation

- Targeted architecture tests: `python -m pytest tests/test_analysis_enrichment_pipeline.py tests/test_analysis_service_fallback.py tests/test_institutional_edge.py tests/test_institutional_edge_response.py -q` -> `5 passed`
- Compile/import validation: `python -m compileall core tests`
- Full local test suite: `python -m pytest -q` -> `112 passed`
- FastAPI smoke:
  - `POST /v1/engine/analyze` -> `200`
  - `metadata.product_surface` present
  - `metadata.institutional_edge` present
  - `data.cards` includes `institutional_edge`

## v9.5.0 - 2026-04-26

### Added

- Added `core/institutional_edge.py`, a deterministic institutional-readiness layer that scores each signal on:
  - evidence quality
  - execution feasibility
  - risk control
  - edge distinctiveness
  - capacity and slippage budget
  - red-team opposing thesis
- Added additive response fields for institutional review:
  - `metadata.institutional_edge`
  - `metadata.product_surface.institutional_edge`
  - `data.analysis.institutional_edge`
  - `data.signal_brief.institutional_grade`
  - `data.signal_brief.institutional_grade_score`
  - `data.signal_brief.institutional_approval_state`
  - `data.cards[].card_type == "institutional_edge"`
- Added frontend-ready differentiation fields:
  - `approval_state`
  - `capacity`
  - `blockers`
  - `kill_conditions`
  - `red_team`
  - `moat_vs_retail_ai`

### Changed

- Updated the productized event envelope so institutional edge information appears in the analysis object and card stack without changing existing field names.
- Updated `README.md` to explain how the engine differs from retail brokerage AI summaries such as real-time issue ranking, news/disclosure summaries, and earnings-call comprehension tools.

### Validation

- Targeted institutional tests: `python -m pytest tests/test_analysis_service_fallback.py tests/test_institutional_edge.py tests/test_institutional_edge_response.py -q` -> `4 passed`
- Full local test suite: `python -m pytest -q` -> `111 passed`
- Compile/import validation: `python -m compileall .`
- FastAPI smoke:
  - `POST /v1/engine/analyze` -> `200`
  - `metadata.institutional_edge` present
  - `data.analysis.institutional_edge` present
  - `data.cards` includes `institutional_edge`

## v9.4.10 - 2026-04-24

### Fixed

- Fixed the live persistence bootstrap mismatch in `sql/ai_engine_event_store_schema.sql`:
  - `ai_replay_tracks` now enforces `run_id` uniqueness to match the repository's `ON CONFLICT (run_id)` write path
  - bootstrap now includes an idempotent deduplication migration that keeps the latest replay row per `run_id` before adding the uniqueness constraint
- Fixed the real PostgreSQL `analyze-and-persist` failure caused by the missing replay uniqueness constraint. The engine can now persist event envelopes, replay rows, and run bundles end to end against the local PostgreSQL instance.

### Added

- Added regression coverage in `tests/test_event_store_repository.py` for:
  - replay upsert SQL continuing to target `ON CONFLICT (run_id)`
  - schema SQL continuing to ship the `ai_replay_tracks_run_id_key` migration and deduplication block

### Validation

- Targeted repository regression: `python -m pytest tests/test_event_store_repository.py -q` -> `15 passed`
- Full local test suite: `python -m pytest -q` -> `108 passed`
- Real PostgreSQL bootstrap verification:
  - `POST /v1/engine/admin/bootstrap-schema` -> `200`
  - `POST /v1/engine/analyze-and-persist` -> `200`
  - `GET /v1/engine/runs` -> persisted run returned successfully
  - `GET /v1/engine/runs/{run_id}` -> full run bundle returned successfully
- Database invariant check on the local PostgreSQL instance:
  - `ai_replay_tracks_run_id_key` exists
  - `ai_replay_tracks` duplicate `run_id` count = `0`
- Remaining readiness blocker on this machine:
  - `GEMINI_API_KEY` is still not configured, so `/health/ready` remains degraded for live LLM access

## v9.4.9 - 2026-04-24

### Fixed

- Fixed external readiness semantics in `api/routers/health.py` so `/health/ready` now reports missing `GEMINI_API_KEY` and database dependency failures via additive `checks`.
- Fixed PostgreSQL degraded-environment behavior in `db/postgres_executor.py`:
  - added a 2-second connect timeout
  - added a 15-second fast-fail cooldown after a failed connection attempt
  - replaced unreadable dependency-error text with clear install instructions
- Fixed repeated-request latency when PostgreSQL is down: after the first failed DB attempt, subsequent readiness and analyze calls fast-fail instead of blocking on repeated connection timeouts.

### Added

- Added `requirements.txt` for local environment bootstrap.
- Added `DATABASE_CONNECT_TIMEOUT_SECONDS` and `DATABASE_FAILURE_COOLDOWN_SECONDS` to `.env.example`.
- Added regression coverage for:
  - health readiness dependency checks in `tests/test_health_ready.py`
  - PostgreSQL timeout/cooldown behavior in `tests/test_postgres_executor.py`

### Validation

- Installed `psycopg 3.3.3` and `psycopg-binary 3.3.3` into the current Python environment for runtime verification.
- Local test suite: `107 passed`
- Compile/import validation: `python -m compileall .`
- External smoke on the current machine:
  - first `/health/ready`: `503` in `4.251s`
  - second `/health/ready`: `503` in `0.004s`
  - `/v1/engine/analyze`: `200` in `0.015s` after DB failure cooldown engaged
- Remaining environment blockers on this machine:
  - `GEMINI_API_KEY` is not configured
  - PostgreSQL at `localhost:5432` is not reachable
  - live LLM + persistence readiness remains `degraded` until those are provided
## v9.4.8 - 2026-04-23

### Fixed

- Fixed a structural runtime bug in `main.py` so request dispatch now uses the app-scoped `AnalysisService` instance instead of recreating a fresh service through `run_analysis()` on every call.
- Fixed `create_app()` dispatch isolation in `main.py` by capturing the local FastAPI app in the dispatch closure. This prevents module-global app leakage in tests and any multi-app runtime setup.
- Fixed `/stats` accounting in `api/routers/health.py`:
  - `route_counts` now reports route-profile usage from token telemetry
  - `llm_route_counts` now reports actual model routing from `AnalysisService.route_counts`
  - flash/review routing rates now derive from real route-profile usage instead of model-name keys
- Fixed LLM parse/schema hard-failure behavior in `core/analysis_service.py` so invalid model JSON now falls back to a neutral result with `metadata.llm_error` instead of raising and terminating the request.

### Added

- Added regression coverage for:
  - app-local dispatch isolation in `tests/test_runtime_dispatch_paths.py`
  - neutral fallback on invalid LLM JSON in `tests/test_analysis_service_fallback.py`
  - corrected `/stats` route-profile vs model-count semantics in `tests/test_stats_token_usage.py`
- Updated API regression coverage in:
  - `tests/test_main_productized_response.py`
  - `tests/test_control_plane_api.py`
  - `tests/test_main_persistence_api.py`

### Validation

- Local test suite: `102 passed`
- Compile/import validation: `python -m compileall .`
- Fresh app smoke:
  - `/v1/engine/analyze` returned `200`
  - `/stats` correctly reported `route_counts={'economy': 1}` and `llm_route_counts={'gemini-3.1-flash-preview': 1}` after a single analyze call

## v9.4.7 - 2026-04-22

### Added

- Added `NASDAQ100_AGGRESSIVE_ROTATION_SECTORS` in `core/strategy_track_rules.py` so the aggressive Nasdaq track can add samples only through selected reversal-rotation sectors:
  - `COMMUNICATION_SERVICES`
  - `CONSUMER_DEFENSIVE`
  - `BASIC_MATERIALS`
- Added focused runtime regression coverage for:
  - whitelisted aggressive Nasdaq rotation into `REVERSAL_CATALYST`
  - non-whitelisted Nasdaq sectors staying blocked from the reversal sleeve
- Added updated artifacts:
  - `data/backtests/nasdaq100_aggressive_20200101_20251231_probe_v8.json`
  - `data/backtests/nasdaq100_aggressive_20200101_20251231_probe_v8.md`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v7.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v7.md`

### Changed

- Refined `strategies/orchestrator.py` so Nasdaq aggressive no longer uses a broad non-reversal fallback. Instead, it rotates into `REVERSAL_CATALYST` only when the sector belongs to the allowed reversal-rotation sleeve.
- Kept the rest of the aggressive redesign intact:
  - `SP500 aggressive` remains the selective `PEAD` research track
  - conservative tracks remain unchanged

### Validation

- Local test suite: `100 passed`
- Nasdaq aggressive probe rerun completed for `2020-01-01` through `2025-12-31`
- Full exact-range acceptance matrix rerun completed again for `2020-01-01` through `2025-12-31`
- `nasdaq100_aggressive` improved from the prior v9.4.6 result:
  - `47` trades / `70.2128%` win rate / `0.6610%` avg trade / `1.9117` PF / `3.0099` Sharpe / `-9.4087%` MDD / `34.1377%` total return
- To:
  - `60` trades / `71.6667%` win rate / `0.7885%` avg trade / `2.1743` PF / `3.7544` Sharpe / `-9.4087%` MDD / `57.1358%` total return
- Promotion result:
  - both aggressive tracks now pass the aggressive research thresholds while remaining `research_canary_only` by design
  - conservative production candidates remain unchanged

## v9.4.6 - 2026-04-22

### Added

- Added shared aggressive research-track rules in `core/strategy_track_rules.py` for:
  - `NASDAQ100 aggressive` strategy and sector blocking
  - `SP500 aggressive` strategy and sector blocking
- Added aggressive-track regression coverage in:
  - `tests/test_strategy_enhancements.py`
  - `tests/test_research_backtest_service.py`
- Added updated exact-date artifacts:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v6.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v6.md`

### Changed

- Reworked `core/universe_profiles.py` so aggressive overlays are no longer described or configured as threshold-relaxation profiles.
- Hardened `strategies/orchestrator.py` so:
  - `NASDAQ100 aggressive` only keeps selected `REVERSAL_CATALYST` participation and blocks excluded reversal sectors.
  - `SP500 aggressive` only keeps selected `PEAD` participation and blocks excluded PEAD sectors.
- Hardened `services/research_backtest_service.py` with matching aggressive approval rules so runtime and research stay aligned.
- Extended `core/signal_explainer.py` with additive blocked-reason text for the new aggressive research-track filters.

### Validation

- Local test suite: `99 passed`
- Exact-range acceptance matrix rerun completed again for `2020-01-01` through `2025-12-31`
- `nasdaq100_aggressive` improved from:
  - `1034` trades / `47.6789%` win rate / `-0.0230%` avg trade / `0.9866` PF / `-0.0615` Sharpe / `-90.5782%` MDD / `-67.4772%` total return
- To:
  - `47` trades / `70.2128%` win rate / `0.6610%` avg trade / `1.9117` PF / `3.0099` Sharpe / `-9.4087%` MDD / `34.1377%` total return
- `sp500_aggressive` improved from:
  - `3065` trades / `43.2300%` win rate / `-0.4437%` avg trade / `0.7316` PF / `-1.4872` Sharpe / `-100.0%` MDD / `-100.0%` total return
- To:
  - `62` trades / `62.9032%` win rate / `1.1112%` avg trade / `2.0738` PF / `2.5019` Sharpe / `-13.8193%` MDD / `91.1128%` total return
- Promotion result:
  - `sp500_aggressive` now clears aggressive research thresholds but remains `research_canary_only` by design
  - `nasdaq100_aggressive` now clears every aggressive quality threshold except the `trade_count >= 50` sample floor
  - conservative production candidates remained unchanged
## v9.4.5 - 2026-04-22

### Added

- Added additive Nasdaq100 conservative guardrail coverage in:
  - `tests/test_strategy_enhancements.py`
  - `tests/test_research_backtest_service.py`
- Added final exact-date artifacts:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v3.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v3.md`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v4.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v4.md`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v5.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v5.md`

### Changed

- Hardened `strategies/orchestrator.py` with Nasdaq100 conservative overextension blocking for continuation setups.
- Refined the Nasdaq100 conservative gap rule so oversized upside-gap continuation remains blocked, while downside-dislocation `NEWS_BREAKOUT` can still pass when the setup is not overheated.
- Hardened `services/research_backtest_service.py` with matching Nasdaq100 conservative approval rules to keep runtime and research behavior aligned.

### Validation

- Local test suite: `93 passed`
- Exact-range acceptance matrix rerun completed again for `2020-01-01` through `2025-12-31`
- `nasdaq100_conservative` improved from:
  - `145` trades / `48.9655%` win rate / `0.2219%` avg trade / `1.1263` PF / `0.4412` Sharpe / `-40.8479%` MDD
- To:
  - `40` trades / `57.5%` win rate / `0.6346%` avg trade / `1.5052` PF / `1.5914` Sharpe / `-9.9275%` MDD
- `sp500_conservative` remained stable at:
  - `51` trades / `58.8235%` win rate / `0.7349%` avg trade / `1.7775` PF / `2.6416` Sharpe / `-10.4207%` MDD
- Promotion result:
  - `nasdaq100_conservative` now passes all conservative production thresholds and is marked `prod_candidate`
  - `sp500_conservative` remains `prod_candidate`

## v9.4.4 - 2026-04-22

### Added

- Added `core/strategy_track_rules.py` to centralize SP500 conservative continuation guardrails for runtime and research paths.
- Added regression coverage for:
  - SP500 conservative utility-sector continuation blocking
  - SP500 conservative sector-specific composite-floor approval
- Added tuned exact-date artifacts:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned.md`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v2.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy_retuned_v2.md`

### Changed

- Hardened `strategies/orchestrator.py` so SP500 conservative utility-sector continuation setups fall back directly to `SENTIMENT_ONLY` instead of leaking into `PEAD`.
- Hardened `services/research_backtest_service.py` with SP500 conservative sector-aware composite floors for `GAP_AND_GO` approval.
- Extended `core/signal_explainer.py` with additive blocked-reason text for the new SP500 conservative guardrails.

### Validation

- Local test suite: `89 passed`
- Exact-range acceptance matrix rerun completed again for `2020-01-01` through `2025-12-31`
- SP500 conservative metrics improved from:
  - `109` trades / `55.9633%` win rate / `0.2383%` avg trade / `1.2162` PF / `0.9477` Sharpe / `-20.6825%` MDD
- To:
  - `51` trades / `58.8235%` win rate / `0.7349%` avg trade / `1.7775` PF / `2.6416` Sharpe / `-10.4207%` MDD
- Promotion result:
  - `sp500_conservative` now passes all conservative production thresholds and is marked `prod_candidate`

## v9.4.3 - 2026-04-21

### Added

- Added exact date-range support to `tools/market_interest_backtest.py` with `--start-date` and `--end-date`.
- Added additive research-service report fields:
  - `start_date`
  - `end_date`
  - `data_window_label`
- Added regression coverage for exact-range lookback calculation and report payloads.
- Added exact-range artifacts:
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy.json`
  - `data/backtests/acceptance_matrix_v94_20200101_20251231_proxy.md`

### Changed

- Extended `services/research_backtest_service.py` so proxy and replay backtests can run against explicit calendar ranges instead of only yfinance `period` windows.
- Filtered replay samples by exact event date when a custom range is provided.
- Cleaned proxy backtest warnings by clipping zero dollar-volume before `log10` and normalizing numeric optional columns before fill defaults.

### Validation

- Local test suite: `87 passed`
- Exact-range acceptance matrix run completed for `2020-01-01` through `2025-12-31`
- Acceptance summary:
  - `nasdaq100_conservative`: `145` trades, win rate `48.9655%`, avg trade `0.2219%`, Sharpe `0.4412`, MDD `-40.8479%`
  - `sp500_conservative`: `109` trades, win rate `55.9633%`, avg trade `0.2383%`, Sharpe `0.9477`, MDD `-20.6825%`
  - Aggressive tracks remained non-promotable with materially worse drawdown and expectancy
  - Selected conservative candidate: `sp500_conservative`, but still below production thresholds

## v9.4.2 - 2026-04-21

### Changed

- Hardened `strategies/orchestrator.py` with profile-aware strategy filtering, safer fallback routing, trend-up confirmation checks, SP500 PEAD quality gating, and conservative risk-off regime blocking.
- Made `AnalyzeRequest.universe_profile` effective by threading it through runtime dispatch into live strategy selection.
- Normalized `relative_strength_20d` handling across live strategy logic, signal explanation, MFE/MAE tuning, event-quality scoring, and proxy backtests.
- Updated conservative universe profiles to block `risk_off` tactical entries instead of relying on an unused legacy regime label.

### Added

- Added focused regression coverage for profile-aware hold floors, SP500 PEAD fallback behavior, risk-off conservative blocking, and proxy backtest RS normalization.
- Added reproducibility artifacts:
  - `data/backtests/acceptance_matrix_v94_10y_proxy_final.json`
  - `data/backtests/acceptance_matrix_v94_10y_proxy_final.md`
  - `data/backtests/acceptance_matrix_v94_10y_proxy_rerun.json`
  - `data/backtests/acceptance_matrix_v94_10y_proxy_rerun.md`

### Validation

- Local test suite: `82 passed`
- 10-year acceptance rerun highlights versus the original baseline:
  - `nasdaq100_conservative`: avg trade `-0.1692% -> +0.0349%`, Sharpe `-0.4052 -> +0.0726`, MDD `-91.5271% -> -76.3252%`
  - `sp500_conservative`: avg trade `-0.4082% -> -0.1708%`, Sharpe `-0.9854 -> -0.7483`, MDD `-99.9978% -> -64.6129%`
  - Aggressive tracks improved modestly but remain non-promotable
  - Final rerun matched the final artifact exactly on scenario metrics
## v9.4.1 - 2026-04-20

### Added

- Added `models/canonical_models.py` for additive canonical company/event/transcript/guidance/overlay/source-health inputs.
- Added `services/canonical_bundle_service.py` to normalize canonical bundles into compact feature bundles and source-health summaries.
- Added `core/signal_brief.py` to emit a fixed `signal_brief` contract for frontend and API consumers.
- Added tests:
  - `tests/test_canonical_bundle_service.py`
  - refreshed `tests/test_event_payload_builder.py`

### Changed

- Extended `AnalyzeRequest` with additive `canonical_bundle` and `source_health` fields.
- Extended `core/analysis_service.py` to derive canonical feature bundles, record source-health telemetry, and inject compact bundle context into prompts.
- Extended `core/prompt_builder.py` to accept `route_profile`, `source_type`, and `feature_bundle_context` without breaking existing callers.
- Extended `core/event_payload_builder.py` to return additive `signal_brief` and `feature_bundle` blocks.
- Extended `GET /stats` with canonical/source-health coverage and stale-source telemetry.
- Extended persistence to store canonical/source-health snapshots and signal briefs.
- Updated `README.md` and `docs/SYSTEM_ARCHITECTURE.md` to document the new contracts.

### Fixed

- Fixed a latent prompt-builder compatibility bug where `core.analysis_service.py` passed `route_profile` and `source_type` keywords not accepted by `core.prompt_builder.build_prompt()`.

### Validation

- Local test suite: `78 passed`

## v9.4.0 - 2026-04-19

### Added

- Added `services/research_backtest_service.py` for v9-native offline proxy/replay/hybrid research runs.
- Added `tools/market_interest_backtest.py` CLI for single-scenario and acceptance-matrix backtests.
- Added populated universe files:
  - `data/universes/nasdaq100_20260412.txt`
  - `data/universes/sp500_20260412.txt`
- Added new tests:
  - `tests/test_universe_profiles_v94.py`
  - `tests/test_research_backtest_service.py`
  - `tests/test_stats_token_usage.py`
- Added runtime token and cost telemetry through `core/token_budgeter.py`.

### Changed

- Reworked `core/universe_profiles.py` to remove unsupported strategy references from the official v9 strategy catalog.
- Locked conservative and aggressive strategy sets to the v9.4 plan.
- Extended `core/gemini_client.py` usage metadata with `estimated_cost_usd`, cache, and coalescing flags.
- Extended `core/analysis_service.py` to record prompt/output/cache/cost stats through `TokenBudgeter`.
- Extended `GET /stats` with additive token/cost/budget fields.
- Updated `core/prompt_builder.py` to use route-aware prompt ceilings.
- Updated `README.md` and `docs/SYSTEM_ARCHITECTURE.md` to document the offline research layer and proxy vs replay boundary.

### Fixed

- Fixed max drawdown calculation so it is based on timestamp-sorted equity progression instead of implicit input ordering.
- Fixed batch market-data download throughput by adding batched yfinance history loading.
- Fixed yfinance cache path issues by forcing cache storage under workspace `data/yfinance_cache`.

### Validation

- Local test suite: `75 passed`
- Live acceptance artifact generated:
  - `data/backtests/acceptance_matrix_v94_proxy.json`
  - `data/backtests/acceptance_matrix_v94_proxy.md`

### Acceptance Summary

- Selected conservative candidate: `sp500_conservative`
- Production-eligible scenarios: none
- Research conclusion: current proxy rule set is not promotion-ready and requires tighter event filtering, stronger continuation confirmation, and replay-grounded calibration before promotion
