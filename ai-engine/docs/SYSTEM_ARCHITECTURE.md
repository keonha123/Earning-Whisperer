# EarningWhisperer AI Engine System Architecture

## Product Identity

EarningWhisperer is a policy-aware, explainable AI decision engine for earnings-call and event-driven trading workflows. This repository owns the AI-engine layer only.

The engine is responsible for:

1. validating inbound market and event context
2. normalizing optional canonical bundles into compact feature bundles
3. generating strategy-aware signal outputs
4. explaining why a signal passed, failed, or was blocked
5. persisting, validating, calibrating, and controlling those decisions

## Layered Architecture

### 1. Ingest Contract Layer

- files: `models/request_models.py`, `models/canonical_models.py`
- role: validate inbound analyze payloads, optional canonical entities, and source health snapshots
- main contracts:
  - `AnalyzeRequest`
  - `MarketData`
  - `CanonicalEventBundle`
  - `CanonicalSourceHealth`

### 2. Canonical Normalization Layer

- files: `services/canonical_bundle_service.py`
- role: derive compact `feature_bundle` summaries from canonical entities and source-health snapshots
- outputs:
  - `feature_bundle`
  - `source_health_summary`
  - prompt-safe context strings

### 2.5 Signal DataHub Layer

- files: `core/signal_data_hub.py`
- role: standardize runtime feature/source topics for freshness, reuse, and observability
- outputs:
  - `feature_bundle:{ticker}` topic records
  - `source_health:{source}` topic records
  - TTL/stale/cache/coalescing statistics
- boundary: in-process runtime telemetry only; it does not fetch external data or replace upstream adapters

### 3. Feature Extraction And Signal Construction

- files: `core/analysis_service.py`, `core/prompt_builder.py`, `core/gemini_client.py`
- role: phase-1 scoring, LLM routing, prompt generation, Gemini usage capture, response parsing, and neutral fallback

### 3.5 Post-LLM Enrichment Pipeline

- files: `core/analysis_enrichment.py`, `core/trade_plan.py`, `core/options_advisor.py`, `core/signal_explainer.py`, `core/product_surface.py`, `core/institutional_edge.py`
- role:
  - strategy selection
  - hold-day and risk-flag assignment
  - trade-plan generation
  - options overlay generation
  - explanation generation
  - product surface generation
  - institutional readiness scoring
- pattern: pipeline/facade boundary around deterministic enrichment after the live model call

### 4. Strategy Scoring Layer

- files: `strategies/orchestrator.py`, `core/universe_profiles.py`, `core/event_quality.py`, `core/mfe_mae_tuner.py`
- role: convert transcript/event interpretation into strategy choice, hold days, risk flags, and track-specific restrictions

### 5. Runtime Control Layer

- files: `services/runtime_dispatch_service.py`, `services/control_plane_service.py`
- role: apply runtime blocking, rollout bucket selection, active patch resolution, and emergency controls

### 6. Explanation And Product Contract Layer

- files: `core/signal_explainer.py`, `core/product_surface.py`, `core/signal_brief.py`, `core/event_payload_builder.py`
- role:
  - generate reasons, risks, and blocked-reason payloads
  - build fixed `signal_brief` summaries
  - assemble frontend-ready cards and replay payloads
  - expose institutional edge payloads additively

### 7. Persistence Layer

- files: `repositories/event_store_repository.py`, `sql/ai_engine_event_store_schema.sql`, `db/postgres_executor.py`
- role: store events, runs, feature snapshots, signal briefs, replay tracks, rollout history, regression reports, and calibration proposals

### 8. Query, Metrics, And Learning Layer

- files: `services/regression_service.py`, `services/calibration_service.py`, `api/routers/query.py`
- role: metrics overview, scorecard, drift, leaderboard, regression diffs, proposal retrieval, and promotion evidence

### 9. Offline Research Layer

- files: `services/research_backtest_service.py`, `tools/market_interest_backtest.py`, `data/universes/*`, `data/backtests/*`
- role: run broad-universe proxy backtests, replay validation, conservative/aggressive acceptance comparisons, and artifact generation

### 10. API Layer

- files: `api/routers/*.py`, `api/dependencies.py`, `main.py`
- role: expose stable HTTP contracts without embedding strategy logic in route handlers

## Runtime Flow

### Analyze Flow

```text
POST /v1/engine/analyze
  -> api/routers/analysis.py
  -> services/runtime_dispatch_service.dispatch_analysis()
  -> core.analysis_service.run_analysis()
  -> services.canonical_bundle_service.CanonicalBundleService.build_feature_bundle()
  -> core.signal_data_hub.SignalDataHub.record_feature_bundle()
  -> core.prompt_builder.build_prompt()
  -> Gemini routing + response validation
  -> core.analysis_enrichment.AnalysisEnrichmentPipeline
  -> strategy scoring + trade plan + explanation + institutional edge
  -> core.event_payload_builder.build_engine_event_response()
  -> core.signal_brief.build_signal_brief()
  -> services.control_plane_service.apply_runtime_controls()
  -> response envelope
```

### Analyze And Persist Flow

```text
POST /v1/engine/analyze-and-persist
  -> analyze flow
  -> repositories.event_store_repository.save_event_envelope()
  -> ai_events / ai_analysis_runs / ai_feature_snapshots / ai_signal_explanations / ai_trade_plans / ai_cards / ai_paywall_surfaces / ai_replay_tracks
```

### Control / Calibration / Regression Flow

```text
control endpoint
  -> api/routers/control.py
  -> services/control_plane_service.py
  -> repositories/event_store_repository.py

calibration or regression endpoint
  -> api/routers/calibration.py or api/routers/regression.py
  -> service layer
  -> repository persistence and retrieval
```

### Offline Research Flow

```text
tools/market_interest_backtest.py
  -> services.research_backtest_service.ResearchBacktestService
  -> yfinance OHLCV/VIX pull
  -> deterministic proxy GeminiAnalysisResult generation
  -> choose_strategy() + track-level gating + hold simulation
  -> price_proxy and/or event_replay result blocks
  -> JSON / Markdown artifacts under data/backtests/
```

## Key Contracts

### Additive Analyze Inputs

- `canonical_bundle`
- `source_health`

### Additive Analyze Outputs

- top-level `signal_brief`
- `data.signal_brief`
- `data.analysis.feature_bundle`
- `data.analysis.signal_data_hub`
- `data.analysis.institutional_edge`
- `analysis.metadata.feature_bundle`
- `analysis.metadata.source_health_summary`
- `analysis.metadata.signal_data_hub`
- `analysis.metadata.institutional_edge`

## Design Patterns And Algorithm Choices

- Thin router pattern: HTTP modules only validate and dispatch; engine logic stays in core/services.
- Pipeline pattern: the model call and deterministic enrichment are separate stages so each can be tested and changed independently.
- Strategy pattern: `strategies/orchestrator.py` selects among PEAD, news breakout, momentum, gap, reversal, squeeze, IV decay, and sentiment fallback logic.
- Policy overlay pattern: runtime control applies emergency states, active patches, rollout buckets, and blocked reasons after the base signal is built.
- Repository pattern: PostgreSQL access is centralized in `EventStoreRepository`; SQL bootstrap stays in `sql/ai_engine_event_store_schema.sql`.
- Deterministic scoring: institutional edge uses bounded weighted subscores for evidence, execution, risk, edge distinctiveness, confidence, and actionability.
- Runtime data hub: feature/source topics use TTL policies and safe stale handling so observability and future adapters do not need to duplicate freshness logic.
- Fail-closed enrichment: if institutional edge generation fails, the signal remains available but the institutional package degrades to `research_only`.

### Additive `/stats` Outputs

- `canonical_bundle_rate`
- `source_health_rate`
- `stale_source_rate`
- `source_health`
- `signal_data_hub`
- `datahub_topic_count`
- `datahub_cache_hit_rate`
- `datahub_stale_topic_rate`
- `datahub_coalesced_hit_rate`

## Persistence Additions

The current schema also stores:

- `ai_feature_snapshots.canonical_bundle_json`
- `ai_feature_snapshots.source_health_json`
- `ai_signal_explanations.signal_brief_json`

## Validation State

Engineering validation:

- `python -m pytest -q`
- current result: `116 passed`

Research validation:

- artifact: `data/backtests/acceptance_matrix_v94_proxy.json`
- artifact: `data/backtests/acceptance_matrix_v94_proxy.md`
- current live proxy result: no track passed production promotion thresholds

That means the architecture, persistence, observability, institutional-readiness, and research loops are in place. Live promotion should still depend on replay-ground regression evidence, not proxy backtest output alone.
