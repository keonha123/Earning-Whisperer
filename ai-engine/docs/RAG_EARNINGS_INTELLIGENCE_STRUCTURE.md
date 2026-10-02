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

- The retriever uses Qdrant when configured and falls back to deterministic in-memory BM25 retrieval when the service or dependency is unavailable.
- PostgreSQL stores evidence metadata and source text; Qdrant stores the dense index behind the same `hyeongyu`-compatible facade.
- RAG decision is heuristic by default to avoid an extra LLM call per chunk.
- External evidence from canonical bundles, SEC filings, yfinance news, IR URLs, transcript PDFs, and explicit evidence documents is normalized through one ingestion service.
- Company impact relationships, executive profiles, and transcript speaker metadata are persisted separately and injected as evidence when relevant.
- The normal analyze path performs one external retrieval and reuses the same citations for prompt context and confidence policy.
- External evidence from `canonical_bundle.metadata.external_documents` or `evidence_documents` is automatically upserted.
- Earnings-call chunks are stored after analysis so later chunks can compare against prior remarks without look-ahead leakage.
- Qdrant repositories fail fast when the configured embedding dimension differs from the existing collection dimension.

## Live News Fact Check Service

`LiveNewsFactCheckService` is an AI Engine service that remains separate from the normal analyze path. `submit_sentence` accepts one finalized sentence with ticker, timestamp, and a monotonic sentence sequence. It buffers sentences per ticker in memory and runs fact-checking only after three new sentences have accumulated. `sentence_sequence=0` starts a new ticker session and clears any stale partial buffer. Partial one- or two-sentence buffers are discarded when the session ends.

The first Gemini call extracts at most two atomic, news-verifiable claims per sentence and six per batch. Valid claims are embedded together in one OpenAI request, but each vector is searched independently using the source sentence timestamp. A second Gemini call verifies all evidence-backed claims in one request with claim-scoped evidence IDs. Claims without evidence are returned as `INSUFFICIENT_EVIDENCE` without the second call.

The service gates evidence using pure semantic relevance: one strongly relevant article or two moderately relevant articles from independent publishers. Article importance is not used by the fact-check retriever, Qdrant payload, or live fact-check evidence response. Each claim result is `SUPPORTED`, `CONTRADICTED`, or `INSUFFICIENT_EVIDENCE`, with a Korean explanation and exact news citations.

External news vectors use `EXTERNAL_EMBEDDING_*`, while transcript vectors use `EMBEDDING_*`. Both support hash, OpenAI, and Gemini through the same strict provider factory. When changing `EXTERNAL_EMBEDDING_VERSION` or `EMBEDDING_VERSION`, rebuild a versioned collection and replay the applicable source documents. Embedding versions are recorded as metadata and do not filter searches; compatible existing points remain searchable. The live service is exposed at `/v1/engine/live-fact-check/sentence`.

Transcript ingestion is exposed at `POST /api/v1/integration/collector/earnings-transcripts`; comparison is exposed at `POST /v1/engine/transcript/diff`. See `transcript-assistant.md` for translation and selected-segment questions.

Transcript indexing uses every speaker turn and independent `TRANSCRIPT_CHUNK_SIZE_CHARS` / `TRANSCRIPT_CHUNK_OVERLAP_CHARS` settings (600 / 80 by default). Changing these values requires transcript reindexing but does not change news chunking. `tools/reindex_transcripts.py` previews source JSON and can populate a new local collection without mutating existing collections. LLM comparison failures return unverified excerpts (`change_type=mixed`, confidence zero), never a word-count-based assertion of improvement or deterioration.

## Backtest Artifact Policy

Raw files under `data/backtests/*.json` and `data/backtests/*.md` are generated artifacts and are ignored by default. Keep only `data/backtests/.gitkeep` in source control unless a specific small summary artifact is intentionally needed for documentation.

## Persistent Live Earnings Sessions

The video-style trading-room flow is exposed as a persistent session orchestrator rather than another standalone scoring endpoint. A session owns transcript order, speaker identity, fact-check progress, claim history, omission events, scorecard dimensions, and the final trading recommendation.

The authoritative fact-check path is `EvidenceRetrievalService`; the session layer does not create a second verdict algorithm. Each finalized signal is persisted before Redis publication and carries the deterministic ID `live-session:{session_id}`. Repeating the finalize endpoint returns the stored result without publishing a second signal.

The local JSON repository is intended for one AI-engine process and offline/demo recovery. Production multi-worker deployments should enable PostgreSQL mirroring and route a given session consistently to one worker. Broker execution remains outside this service.
