# Legacy GitHub Compatibility Spec

Version: v9.5.9

This document defines how the v9 AI engine remains compatible with the non-AI-engine components from `keonha123/Earning-Whisperer`.

References:

- Original repository: https://github.com/keonha123/Earning-Whisperer
- Gemini models: https://ai.google.dev/gemini-api/docs/models
- Gemini SDK libraries: https://ai.google.dev/gemini-api/docs/libraries

## Compatibility Boundary

The backend, frontend, data pipeline, and trading terminal contracts are not changed. The AI engine adds a compatibility layer that accepts the original HTTP payload and publishes the original Redis raw-signal shape.

The v9-native endpoints remain available:

- `POST /v1/engine/analyze`
- `POST /analyze`
- `POST /v1/engine/events/persist`
- `POST /v1/engine/analyze-and-persist`

The original-compatible endpoint is:

- `POST /api/v1/analyze`

## Original Data Pipeline Input

```json
{
  "ticker": "TSLA",
  "text_chunk": "Margins compressed and demand was softer than expected.",
  "sequence": 7,
  "timestamp": 1778600000,
  "is_final": false
}
```

Required fields:

- `ticker`: symbol
- `text_chunk`: STT transcript chunk
- `sequence`: chunk sequence
- `timestamp`: Unix epoch seconds
- `is_final`: session-end flag

Optional additive fields:

- `market_data`
- `section_type`
- `source_type`
- `request_priority`
- `route_profile`
- `needs_review`
- `universe_profile`

## Internal Mapping

| Legacy field | v9 field |
| --- | --- |
| `ticker` | `AnalyzeRequest.ticker` |
| `text_chunk` | `AnalyzeRequest.current_chunk` |
| `sequence` | `AnalyzeRequest.chunk_sequence` |
| `timestamp` | `AnalyzeRequest.request_metadata.original_timestamp` |
| `is_final` | `AnalyzeRequest.is_final` |

If market data is not provided, the adapter creates `MarketData(ticker=ticker)` and lets the v9 engine use neutral defaults.

## Redis Raw Signal Output

Channel:

```text
trading-signals
```

Required message fields:

```json
{
  "ticker": "TSLA",
  "raw_score": -0.62,
  "rationale": "Demand softened and margin pressure increased.",
  "text_chunk": "Margins compressed and demand was softer than expected.",
  "timestamp": 1778600000,
  "is_session_end": false
}
```

Optional fields:

- `action`
- `confidence`
- `strategy`
- `hold_days`
- `model_route`
- `execution_allowed`
- `blocked_reason_ko`
- `signal_brief`
- `engine_event_id`
- `schema_version`

The enriched v9 envelope is published separately to:

```text
trading-signals-enriched
```

## Failure Behavior

Redis is not allowed to break analysis. If Redis is unavailable:

- `/api/v1/analyze` still returns `200` if analysis completed.
- `redis_published=false`
- `enriched_published=false`
- `publish_error` contains the publish failure.
- Failed messages are retained in the in-memory publisher backup queue up to `REDIS_BACKUP_QUEUE_SIZE`.

## Gemini Defaults

The engine uses the official `google-genai` SDK. Defaults are:

- Fast/primary: `gemini-3.1-flash-lite`
- Review/escalation: `gemini-3.1-pro-preview`
- Candidate fallback: `gemini-3.1-pro-preview,gemini-3-flash-preview,gemini-3.1-flash-lite,gemini-2.5-pro`

`gemini-3-pro-preview` is not used as a default because the official Gemini model page marks it as deprecated and shut down on 2026-03-09.

## Environment Settings

```env
REDIS_CHANNEL=trading-signals
REDIS_ENRICHED_CHANNEL=trading-signals-enriched
LEGACY_REDIS_PUBLISH_ENABLED=true
REDIS_ENRICHED_PUBLISH_ENABLED=true
REDIS_BACKUP_QUEUE_SIZE=100
REDIS_SOCKET_TIMEOUT_SECONDS=1.0
GEMINI_PRIMARY_MODEL=gemini-3.1-flash-lite
GEMINI_REVIEW_MODEL=gemini-3.1-pro-preview
```
