# RAG Earnings Intelligence Structure

## Summary

The AI engine now uses the `hyeongyu` branch RAG architecture as the standard retrieval layer:

```text
AnalyzeRequest
  -> Phase1 scorer
  -> rolling context
  -> rag_decision
  -> external_retriever.retrieve
  -> relevance_check
  -> prompt_builder(EXTERNAL_EVIDENCE)
  -> Gemini primary/review
  -> transcript enhancer
  -> strategy/explanation/trade plan
```

The implementation keeps current v9 API contracts additive-only. Existing `/v1/engine/*`, `/api/v1/analyze`, and Redis `trading-signals` outputs remain compatible.

## Core Files

- `models/rag_models.py`: `ExternalRagDecision`, `ExternalQueryRewrite`
- `core/external_retriever.py`: `ExternalDocument`, `ExternalRetrievedDocument`, `ExternalRetrieverFacade`
- `src/graph/nodes/rag_decision.py`: RAG routing decision
- `src/graph/nodes/retrieve.py`: retrieval node
- `src/graph/nodes/relevance_check.py`: evidence availability check
- `core/prompt_builder.py`: inserts `EXTERNAL_EVIDENCE` into the analysis prompt
- `core/analysis_service.py`: runs the RAG nodes inside the normal analyze path

## Earnings Intelligence API

Additional frontend/backend endpoint:

- `POST /v1/engine/earnings/intelligence`
- `POST /api/v1/earnings/intelligence`

Input includes:

- `ticker`
- `event_text`
- optional `question` / `answer`
- optional `external_documents`
- optional `related_tickers`
- optional `market_data`
- optional `direction_hint` / `confidence_hint`

Output includes:

- `retrieved_evidence`
- `fact_checks`
- `claim_diffs`
- `omission_evasion`
- `impact_chain`
- `risk_plan`
- `summary_ko`
- `warnings`

## Design Notes

- The retriever uses Qdrant when configured and falls back to deterministic in-memory BM25 retrieval when the service or dependency is unavailable.
- PostgreSQL stores evidence metadata and source text; Qdrant stores the dense index behind the same `hyeongyu`-compatible facade.
- RAG decision is heuristic by default to avoid an extra LLM call per chunk.
- External evidence from canonical bundles, SEC filings, yfinance news, IR URLs, transcript PDFs, and explicit evidence documents is normalized through one ingestion service.
- Company impact relationships, executive profiles, and transcript speaker metadata are persisted separately and injected as evidence when relevant.
- Earnings-call chunks are stored after analysis so later chunks can compare against prior remarks without look-ahead leakage.

## Backtest Artifact Policy

Raw files under `data/backtests/*.json` and `data/backtests/*.md` are generated artifacts and are ignored by default. Keep only `data/backtests/.gitkeep` in source control unless a specific small summary artifact is intentionally needed for documentation.

## Persistent Live Earnings Sessions

The video-style trading-room flow is exposed as a persistent session orchestrator rather than another standalone scoring endpoint. A session owns transcript order, speaker identity, fact-check progress, claim history, omission events, scorecard dimensions, and the final trading recommendation.

The authoritative fact-check path is `EvidenceRetrievalService`; the session layer does not create a second verdict algorithm. Each finalized signal is persisted before Redis publication and carries the deterministic ID `live-session:{session_id}`. Repeating the finalize endpoint returns the stored result without publishing a second signal.

The local JSON repository is intended for one AI-engine process and offline/demo recovery. Production multi-worker deployments should enable PostgreSQL mirroring and route a given session consistently to one worker. Broker execution remains outside this service.
