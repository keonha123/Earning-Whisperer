# Architecture And Algorithm Notes

## Goal

The AI engine is structured as an event-driven decision engine, not a retail summary tool. The main design goal is to keep model reasoning, deterministic strategy logic, operational controls, and product payloads independently testable.

## Runtime Architecture

```text
AnalyzeRequest
  -> API router
  -> Runtime dispatch service
  -> AnalysisService
     -> canonical feature bundle
     -> signal data hub topic record
     -> phase-1 scorer
     -> LLM router
     -> prompt builder
     -> Gemini client
     -> schema validation / neutral fallback
  -> AnalysisEnrichmentPipeline
     -> strategy orchestrator
     -> trade plan
     -> options advice
     -> signal explanation
     -> product surface
     -> institutional edge
  -> Event payload builder
  -> Runtime control overlay
  -> response / persistence
```

## Selected Design Patterns

- Adapter: FastAPI routers adapt HTTP payloads into internal contracts.
- Facade: `AnalysisService` exposes one analysis entry point while hiding model routing and context assembly.
- Pipeline: `AnalysisEnrichmentPipeline` applies deterministic post-LLM enrichment in a fixed order.
- Data hub: `SignalDataHub` standardizes runtime feature/source topics with TTL freshness, stale handling, and cache-efficiency metrics.
- Strategy: `strategies/orchestrator.py` chooses the active trading logic based on market/event context.
- Shared policy helpers: `core/strategy_track_rules.py` keeps live strategy selection and research approval aligned.
- Policy overlay: runtime control applies kill switches, suppressions, patches, rollouts, and calibration after the base signal exists.
- Repository: `EventStoreRepository` isolates PostgreSQL persistence and query shape.
- Artifact workflow: offline backtests write JSON/Markdown artifacts instead of adding latency to live APIs.

## Core Algorithms

- LLM routing: fast route first, review route for higher uncertainty or requested review.
- Phase-1 scoring: a configurable hybrid combines deterministic earnings/market features with local FinBERT sentiment; direction conflicts reduce confidence and missing model runtimes fall back to the heuristic path.
- Strategy selection: rule-based strategy router maps event state into PEAD, news breakout, momentum carry, gap, reversal, squeeze, IV decay, or sentiment fallback.
- Track-specific guardrails: Nasdaq100 conservative now separates continuation setups from a constrained mega-cap quality-reversal sleeve and blocks out-of-scope reversals before promotion.
- Research risk governor: the offline approval path applies loss-streak and drawdown cooldown logic for Nasdaq100 conservative before computing promotion metrics.
- Hold tuning: strategy base hold is adjusted by event quality, risk flags, MFE/MAE profile, and track rules.
- Product explanation: rule-based feature contribution and blocked-reason generation keeps frontend payloads non-empty even on neutral/fallback decisions.
- Institutional edge: bounded weighted scoring over evidence quality, execution feasibility, risk control, edge distinctiveness, confidence, and actionability.
- Signal data hub: feature bundles and source-health snapshots are stored as topic records so analysis metadata, stats, and future adapters share one freshness contract.
- Replay validation: persisted replay tracks close the feedback loop for metrics, drift, calibration, and promotion evidence.

## Boundaries

- `core/analysis_service.py` should stay focused on model-call orchestration.
- `core/signal_data_hub.py` should stay focused on in-process topic freshness and data-reuse observability.
- `core/analysis_enrichment.py` owns deterministic post-model enrichment.
- `core/strategy_track_rules.py` owns reusable strategy/profile guardrail predicates.
- `core/event_payload_builder.py` owns response shape mapping.
- `services/runtime_dispatch_service.py` owns runtime overlays and dispatch.
- `repositories/event_store_repository.py` owns persistence only.

## Why This Structure

This separates the parts that change for different reasons:

- Model routing changes when provider cost or model behavior changes.
- Data-hub policy changes when source freshness, dedupe, or cache observability requirements change.
- Strategy logic changes when backtests or replay evidence change.
- Product payloads change when frontend contracts evolve.
- Control policies change when operating risk changes.
- Persistence changes when audit or replay requirements change.

Keeping those boundaries explicit reduces regression risk as features accumulate.
