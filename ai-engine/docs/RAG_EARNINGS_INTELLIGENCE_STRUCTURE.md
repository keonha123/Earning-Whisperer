# RAG Earnings Intelligence Structure

## Summary

The AI engine now uses the `hyeongyu` branch RAG architecture as the standard retrieval layer:

```text
AnalyzeRequest
  -> Phase1 scorer
  -> rolling context
  -> rag_decision
  -> external_retriever.retrieve
  -> evidence_service.merge(request-scoped + external citations)
  -> prompt_builder(RAG_EVIDENCE)
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
- `services/evidence_retrieval_service.py`: merges request-scoped and external citations without persisting transient input
- `core/prompt_builder.py`: inserts one normalized `RAG_EVIDENCE` block into the analysis prompt
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
- The normal analyze path performs one external retrieval and reuses the same citations for prompt context and confidence policy.
- External evidence from `canonical_bundle.metadata.external_documents` or `evidence_documents` is automatically upserted.
- Earnings-call chunks are stored after analysis so later chunks can compare against prior remarks without look-ahead leakage.
- Qdrant repositories fail fast when the configured embedding dimension differs from the existing collection dimension.

## Live News Fact Check Service

`LiveNewsFactCheckService` is an AI Engine service that remains separate from the normal analyze path. `submit_sentence` accepts one finalized sentence with ticker, timestamp, and a monotonic sentence sequence. It buffers sentences per ticker in memory and runs fact-checking only after three new sentences have accumulated. `sentence_sequence=0` starts a new ticker session and clears any stale partial buffer. Partial one- or two-sentence buffers are discarded when the session ends.

The first Gemini call extracts at most two atomic, news-verifiable claims per sentence and six per batch. Valid claims are embedded together in one OpenAI request, but each vector is searched independently using the source sentence timestamp. A second Gemini call verifies all evidence-backed claims in one request with claim-scoped evidence IDs. Claims without evidence are returned as `INSUFFICIENT_EVIDENCE` without the second call.

The service gates evidence using pure semantic relevance: one strongly relevant article or two moderately relevant articles from independent publishers. Article importance is not used by the fact-check retriever, Qdrant payload, or live fact-check evidence response. Each claim result is `SUPPORTED`, `CONTRADICTED`, or `INSUFFICIENT_EVIDENCE`, with a Korean explanation and exact news citations.

External news vectors use `EXTERNAL_EMBEDDING_*`, while transcript vectors use `EMBEDDING_*`. Both support hash, OpenAI, and Gemini through the same strict provider factory. When changing `EXTERNAL_EMBEDDING_VERSION` or `EMBEDDING_VERSION`, rebuild a versioned collection and replay the applicable source documents. Older points without the active embedding version are intentionally excluded. This service has no HTTP route yet.

## Backtest Artifact Policy

Raw files under `data/backtests/*.json` and `data/backtests/*.md` are generated artifacts and are ignored by default. Keep only `data/backtests/.gitkeep` in source control unless a specific small summary artifact is intentionally needed for documentation.
