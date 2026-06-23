# EarningWhisperer AI Engine

EarningWhisperer is the AI-engine layer for event-driven trading decisions. This repository is not a transcript viewer, retail UI, or full backend gateway. The product center is:

- decision: convert earnings-call, news, and event context into structured signals
- explainability: return Korean-friendly reasons, risks, drivers, and block reasons
- control: apply gates, rollout, rollback, calibration, regression, and emergency controls
- research: validate strategy tracks through offline proxy/replay backtests before promotion
- equity research reports: generate structured stock reports for ticker search flows, with Markdown export compatibility
- institutional readiness: score whether a signal is suitable for execution review, not just retail-style summary consumption
- decision assistant: convert signals into sell-first guidance, no-trade explanations, replay confidence badges, execution-cost badges, and counter-thesis cards
- legacy compatibility: accept the original GitHub data-pipeline payload and publish raw Redis signals for the Spring backend

## Hybrid Phase1 FinBERT Runtime

The default Phase1 mode is `hybrid`: deterministic earnings/market features are combined with local FinBERT sentiment before Gemini and RAG processing. FinBERT is an optional heavyweight runtime so the base API and test environment remain lightweight.

```powershell
pip install -r requirements-finbert.txt
```

With `PHASE1_PROVIDER=hybrid`, missing model dependencies or model-load failures automatically degrade to the deterministic heuristic scorer. Runtime state is exposed under `/health`, `/health/ready`, and `/stats` in the `phase1` field. Use `PHASE1_FINBERT_LOCAL_FILES_ONLY=true` in locked-down deployments after pre-caching the model.
## Scope

Included:

- FastAPI AI engine API
- original `keonha123/Earning-Whisperer` non-AI-engine compatibility adapter
- feature extraction, routing, strategy scoring, explanation payloads
- canonical bundle normalization and source-health observability
- in-process signal data hub with TTL freshness, source health, and cache-efficiency telemetry
- PostgreSQL event/evidence persistence and Qdrant-backed evidence retrieval
- replay, metrics, drift, scorecard, leaderboard
- gate patch, rollout, emergency control, calibration, regression
- offline research CLI for proxy/replay/hybrid backtests
- frontend-ready structured equity report API
- SEC/news/IR/transcript evidence ingestion with scheduled synchronization
- data-driven company impact graph, executive profiles, and speaker metadata
- profile-specific Redis channels with a durable retry spool

Excluded:

- frontend UI
- auth and user management
- payment or billing
- upstream live audio capture and STT infrastructure
- broker execution layer

## Current Structure

```text
ai_engine/
|- main.py
|- api/
|  |- dependencies.py
|  `- routers/
|- core/
|  |- analysis_service.py
|  |- analysis_enrichment.py
|  |- decision_assistant.py
|  |- event_payload_builder.py
|  |- institutional_edge.py
|  |- prompt_builder.py
|  |- signal_data_hub.py
|  |- signal_brief.py
|  `- token_budgeter.py
|- services/
|  |- canonical_bundle_service.py
|  |- runtime_dispatch_service.py
|  |- control_plane_service.py
|  |- equity_report_service.py
|  `- research_backtest_service.py
|  |- legacy_contract_adapter.py
|  `- redis_signal_publisher.py
|- repositories/
|  `- event_store_repository.py
|- models/
|  |- canonical_models.py
|  |- equity_report_models.py
|  |- legacy_contract_models.py
|  |- request_models.py
|  |- signal_models.py
|  `- storage_models.py
|- sql/
|  `- ai_engine_event_store_schema.sql
|- tools/
|  `- market_interest_backtest.py
`- tests/
```

## API Surface

Health and runtime:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /stats`

Signal generation:

- `POST /api/v1/analyze` legacy-compatible endpoint for the original data pipeline
- `POST /v1/engine/analyze`
- `POST /analyze` compatibility alias for v9 callers
- `POST /v1/engine/events/persist`
- `POST /v1/engine/analyze-and-persist`

Equity research report:

- `POST /v1/research/equity-report`
- `POST /api/v1/research/equity-report`

Equity report input:

- `ticker`
- `concerns`
- `language`
- `output_format=structured`

Equity report output:

- `structured_report`
- `report_markdown`
- `sources`
- `data_quality`
- `market_snapshot`
- `model`
- `prompt_tokens`
- `output_tokens`
- `estimated_cost_usd`
- `fallback_used`

Legacy analyze input:

- `ticker`
- `text_chunk`
- `sequence`
- `timestamp`
- `is_final`

Legacy Redis output on `trading-signals`:

- `ticker`
- `raw_score` (canonical signed score)
- `ai_score` (same signed value; Spring Backend compatibility alias)
- `rationale`
- `text_chunk`
- `timestamp`
- `is_session_end`

Additive analyze input fields:

- `canonical_bundle`
- `source_health`

Query and replay:

- `GET /v1/engine/runs`
- `GET /v1/engine/runs/{run_id}`
- `GET /v1/engine/events/{event_id}`
- `PATCH /v1/engine/replay/{run_id}`
- `GET /v1/engine/metrics/overview`
- `GET /v1/engine/metrics/scorecard`
- `GET /v1/engine/metrics/drift`
- `GET /v1/engine/metrics/leaderboard`

Control plane:

- gate patch create/list/approve/reject/apply/audit
- rollout create/list/get/advance/abort
- emergency state get/set
- shadow compare
- auto-promotion evaluation

Learning and validation:

- `POST /v1/engine/calibration/run`
- `GET /v1/engine/calibration/proposals`
- `POST /v1/engine/calibration/proposals/{proposal_id}/promote`
- `POST /v1/engine/regression/compare`
- `GET /v1/engine/regression/reports`

## Fixed Signal Brief Contract

Every productized analysis envelope now includes additive `signal_brief` blocks at the top level and under `data.signal_brief`.

Core fields:

- `action`
- `confidence`
- `summary_ko`
- `key_reasons_ko`
- `risk_flags_ko`
- `recommended_hold_days`
- `gate_result`
- `model_version`
- `strategy_id`
- `institutional_grade`
- `institutional_grade_score`
- `institutional_approval_state`
- `sell_first_action`
- `recommended_change_pct`
- `position_intent_ko`
- `no_trade_summary_ko`
- `replay_confidence_badge`
- `execution_badge`
- `counter_thesis_ko`

Related additive analysis metadata:

- `data.analysis.feature_bundle`
- `data.analysis.signal_data_hub`
- `data.analysis.institutional_edge`
- `data.analysis.decision_assistant`
- `metadata.feature_bundle`
- `metadata.institutional_edge`
- `metadata.decision_assistant`
- `metadata.source_health_summary`
- `metadata.signal_data_hub`

## Decision Assistant Layer

The Decision Assistant is the answer to "what should I do with this signal?" It is deterministic and does not add live LLM cost.

It returns:

- `sell_first`: `ADD`, `HOLD`, `REDUCE`, `EXIT`, or `AVOID`
- `no_trade_explainer`: why buying/selling is blocked and what to wait for
- `replay_confidence_badge`: whether the setup is backed by replay/proxy evidence
- `execution_badge`: whether spread, latency, and round-trip cost are within the conservative limit
- `counter_thesis`: opposing argument and conditions that would change the view
- `portfolio_impact_map`: sector, market-cap, QQQ/SPY beta, and relative-strength exposure notes
- `order_draft_preview`: advisory-only draft fields with no broker API call

The payload appears at:

- `metadata.decision_assistant`
- `metadata.product_surface.decision_assistant`
- `data.analysis.decision_assistant`
- `data.cards[].card_type == "decision_assistant"`

This is intentionally different from retail AI summary features: EarningWhisperer explains when not to trade, estimates execution feasibility, shows evidence quality, and gives the counter-thesis before presenting a trading action.

## Institutional Edge Pack

Retail brokerage AI features increasingly focus on real-time issue ranking, news/disclosure summarization, market-move explanations, and earnings-call comprehension. EarningWhisperer now adds a separate institutional layer designed for execution review:

- `evidence_quality`: checks confidence, source coverage, model fallback state, top drivers, and feature contributions
- `execution_feasibility`: checks volume confirmation, liquidity score, spread budget, trade-plan availability, stop, and entry zone
- `risk_control`: checks severe strategy/risk flags and whether the trade has stop/time invalidation
- `edge_distinctiveness`: checks whether the setup is more than a generic news summary by requiring event, volume, relative-strength, and strategy context
- `capacity`: estimates notional capacity from 20-day average volume and a conservative participation-rate budget
- `red_team`: returns the opposing thesis and what would invalidate the trade
- `moat_vs_retail_ai`: exposes the differentiators directly for frontend, pitch, and audit usage

The package is attached additively at:

- `metadata.institutional_edge`
- `metadata.product_surface.institutional_edge`
- `data.analysis.institutional_edge`
- `data.signal_brief.institutional_*`
- `data.cards[].card_type == "institutional_edge"`

## Architecture Pattern

The runtime is organized as a layered pipeline:

- API routers are thin adapters.
- `services/runtime_dispatch_service.py` owns request dispatch, envelope assembly, and runtime control overlay.
- `core/analysis_service.py` owns pre-LLM orchestration: context, feature bundle, phase-1 score, route decision, prompt, model call, and response validation.
- `core/signal_data_hub.py` owns in-process feature/source topic freshness, TTL cache behavior, and data-reuse telemetry.
- `core/analysis_enrichment.py` owns post-LLM enrichment: strategy selection, trade plan, options advice, explanation, product surface, and institutional edge.
- `core/event_payload_builder.py` maps enriched analysis into the stable productized response envelope.

This keeps live model routing, deterministic signal enrichment, product payload assembly, and control overlays as separate boundaries.

Approval states:

- `institutional_actionable`: usable for institutional execution review after normal controls
- `institutional_watch`: evidence is meaningful but not strong enough for immediate execution review
- `research_only`: useful for research, replay, or canary review
- `retail_summary_only`: too weak for institutional use

Persistence additions:

- `ai_feature_snapshots.canonical_bundle_json`
- `ai_feature_snapshots.source_health_json`
- `ai_signal_explanations.signal_brief_json`

## Runtime Token, Cost, And Source Health Stats

`GET /stats` keeps legacy route counters and adds:

- `avg_prompt_tokens`
- `avg_output_tokens`
- `cache_hit_rate`
- `coalesced_request_rate`
- `estimated_total_cost_usd`
- `cost_per_approved_signal`
- `budget_exceeded_count`
- `prompt_budgets`
- `route_usage`
- `canonical_bundle_rate`
- `source_health_rate`
- `stale_source_rate`
- `source_health`
- `signal_data_hub`
- `datahub_topic_count`
- `datahub_cache_hit_rate`
- `datahub_stale_topic_rate`
- `datahub_coalesced_hit_rate`

## Signal DataHub

The engine now has a Python-native `SignalDataHub` that reimplements the useful terminal-style producer/connector concept without copying external licensed code.

Runtime role:

- stores canonical feature bundles under topics such as `feature_bundle:nvda`
- stores source-health snapshots under topics such as `source_health:benzinga_transcripts`
- applies TTL freshness and safe stale handling
- tracks cache hits, misses, stale hits, producer calls, coalesced in-flight requests, and per-source writes
- exposes health through `/stats` and analysis metadata without changing existing response fields

Prompt budget defaults:

- economy: `384`
- standard: `640`
- review: `960`

## v9.4 Research Backtest Layer

The v9.4 backtest runner is deliberately offline and artifact-driven. It is not exposed as a new HTTP research API in this pass.

Modes:

- `price_proxy`: broad-universe proxy backtest using OHLCV and deterministic proxy analysis
- `event_replay`: persisted engine replay validation
- `hybrid`: returns both tracks without mixing them into one metric block

Track policy:

- conservative: only production candidate
- aggressive: research / canary only

Artifacts:

- `data/universes/nasdaq100_20260412.txt`
- `data/universes/sp500_20260412.txt`
- `data/backtests/*.json`
- `data/backtests/*.md`

Example commands:

```bash
python tools/market_interest_backtest.py --tickers-file data/universes/nasdaq100_20260412.txt --universe-profile NASDAQ100 --risk-style CONSERVATIVE --mode proxy --period 9mo --min-history 35 --output-json data/backtests/nasdaq100_conservative_v94.json --output-md data/backtests/nasdaq100_conservative_v94.md --quiet

python tools/market_interest_backtest.py --acceptance-matrix --mode proxy --period 9mo --min-history 35 --output-json data/backtests/acceptance_matrix_v94_proxy.json --output-md data/backtests/acceptance_matrix_v94_proxy.md --quiet
```

Current long-window acceptance result:

- window: `2017-01-20_to_2026-04-26`
- mode: `price_proxy`
- selected production candidate: `nasdaq100_conservative`
- Nasdaq100 conservative: `43` trades, `62.7907%` win rate, `0.6808%` avg trade, `1.6782` profit factor, `2.2955` Sharpe, `-11.4037%` MDD, `31.2770%` total return
- Nasdaq100 aggressive: research/canary only despite strong metrics
- SP500 conservative: hold candidate because MDD still exceeds the conservative production limit

The current Nasdaq100 conservative production candidate uses:

- continuation-only core sector filters for `PEAD`, `NEWS_BREAKOUT`, and `MOMENTUM_CARRY`
- a constrained mega-cap quality-reversal sleeve for `REVERSAL_CATALYST`
- a research risk governor that skips candidates after loss streaks or drawdown shocks
- MIT Quant Bible-inspired validation diagnostics: Wilson win-rate lower bound, Bayesian win-rate smoothing, and bounded fractional Kelly sizing

Operational readiness status:

- DB-backed replay is available through `--use-database-replay`, but the current local database has no closed replay sample set for Nasdaq100 promotion.
- Execution stress validation passes the base and normal broker-cost scenarios.
- Execution stress validation fails high-spread earnings-gap and extreme-spread scenarios, so conservative live/research paths now block entries when estimated all-in execution cost exceeds `0.55%`.
- Latest Nasdaq100 conservative quant-risk artifact remains `prod_candidate` with `47.8595%` Wilson lower win-rate and `6.0587%` fractional Kelly diagnostic.

## Local Run

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
curl http://localhost:8000/stats
```

Readiness prerequisites:

- `GEMINI_API_KEY` must be configured for live model calls
- `psycopg[binary]` must be installed for PostgreSQL-backed readiness and persistence
- `DATABASE_URL` must point at a reachable PostgreSQL instance if persistence APIs are enabled
- `DATABASE_CONNECT_TIMEOUT_SECONDS` defaults to `2` so DB outages fail fast instead of stalling analyze/readiness calls
- `DATABASE_FAILURE_COOLDOWN_SECONDS` defaults to `15` so repeated requests fast-fail while PostgreSQL is still unavailable

## Validation

Validated locally:

```bash
python -m py_compile core/prompt_builder.py core/analysis_service.py core/event_payload_builder.py core/signal_brief.py services/canonical_bundle_service.py repositories/event_store_repository.py api/routers/health.py
python -m pytest -q
```

Latest local result:

- `164 passed`

## Notes

- proxy backtest and replay validation are intentionally separate outputs
- additive-only API changes remain the rule for existing `/v1/engine/*` clients
- the current production candidate is proxy-validated; persisted event replay validation is still required before real-money deployment
## Production Evidence And Intelligence

The v9.6 evidence path supports persistent and offline-safe operation:

```text
SEC filings / yfinance news / IR URLs / transcript PDF
  -> EvidenceIngestionService
  -> PostgreSQL evidence store
  -> Qdrant vector index
  -> evidence-grounded analysis and earnings intelligence
  -> profile-specific Redis channels
  -> durable JSONL retry spool on publish failure
```

Key endpoints:

- `POST /v1/engine/evidence/ingest`
- `POST /v1/engine/evidence/sync`
- `POST /v1/engine/transcripts/ingest`
- `POST /v1/engine/transcripts/upload`
- `GET /v1/engine/evidence/ingestion/status`
- `GET /v1/engine/company-intelligence/{ticker}`
- `POST /v1/engine/company-intelligence/upsert`
- `POST /v1/engine/redis/retry`
- `GET /v1/engine/redis/retry/status`

Run PostgreSQL, Qdrant, Redis, and MySQL from the repository root:

```bash
docker compose -f infra/docker-compose.yml up -d
```

For SEC ingestion, set `EVIDENCE_SEC_USER_AGENT` to an application name and monitored contact email. Scheduled synchronization remains disabled until `EVIDENCE_SYNC_ENABLED=true` and `EVIDENCE_SYNC_TICKERS` are configured.

The AI engine creates order drafts and risk plans only. Broker order execution remains the Trading Terminal responsibility.

## Live Earnings Session API

The live-session layer turns independent chunk analysis into a reconnectable earnings-call workflow:

```text
start session
  -> ingest timestamped speaker chunks
  -> signed AI score per chunk
  -> RAG fact-check ledger and historical claim diff
  -> omission/evasion and speaker telemetry
  -> rolling earnings scorecard
  -> finalize BUY/HOLD/SELL signal
  -> advisory order draft + impact chain + risk plan
  -> persist state and publish one final Redis signal
```

Endpoints:

- `POST /v1/engine/live-sessions`
- `GET /v1/engine/live-sessions`
- `GET /v1/engine/live-sessions/{session_id}`
- `POST /v1/engine/live-sessions/{session_id}/chunks`
- `POST /v1/engine/live-sessions/{session_id}/finalize`

Session state is written atomically under `LIVE_SESSION_STORE_PATH` and mirrored to PostgreSQL when evidence persistence is enabled. Final signals use deterministic IDs (`live-session:{session_id}`), allowing Trading Terminal consumers to deduplicate Redis redelivery. `MANUAL`, `SEMI_AUTO`, and `AUTO_PILOT` are execution-policy hints only; the AI engine never calls a broker. Legacy request values `ONE_CLICK` and `AUTO` are accepted and normalized to the Terminal contract.
