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

- The retriever is memory-first for local compatibility.
- The public facade matches the `hyeongyu` branch so Qdrant can be restored behind the same API later.
- RAG decision is heuristic by default to avoid an extra LLM call per chunk.
- External evidence from `canonical_bundle.metadata.external_documents` or `evidence_documents` is automatically upserted.
- Earnings-call chunks are stored after analysis so later chunks can compare against prior remarks without look-ahead leakage.

## Backtest Artifact Policy

Raw files under `data/backtests/*.json` and `data/backtests/*.md` are generated artifacts and are ignored by default. Keep only `data/backtests/.gitkeep` in source control unless a specific small summary artifact is intentionally needed for documentation.
