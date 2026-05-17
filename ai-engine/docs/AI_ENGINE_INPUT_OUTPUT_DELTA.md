# AI Engine Input/Output Delta

Version: v9.5.9

This document compares the original GitHub AI-engine contract with the v9 AI-engine contract.

## Input Delta

| Area | Original GitHub contract | v9 native contract | v9.5.9 compatibility behavior |
| --- | --- | --- | --- |
| Endpoint | `POST /api/v1/analyze` | `POST /v1/engine/analyze` | Both are available |
| Text field | `text_chunk` | `current_chunk` or alias `prompt` | `text_chunk` is mapped to `current_chunk` |
| Sequence field | `sequence` | `chunk_sequence` | `sequence` is mapped to `chunk_sequence` |
| Timestamp | `timestamp` | envelope timestamp generated at runtime | original timestamp is preserved in `request_metadata.original_timestamp` |
| Market data | not required | `market_data` object | neutral `MarketData(ticker=ticker)` is created when absent |
| Source/section | not required | `source_type`, `section_type` | defaults to `EARNINGS_CALL` and `UNKNOWN` |

## Output Delta

| Area | Original Redis signal | v9 native envelope | v9.5.9 compatibility behavior |
| --- | --- | --- | --- |
| Channel | `trading-signals` | HTTP response/event-store envelope | Raw signal is published to `trading-signals` |
| Score | `raw_score` in `[-1, 1]` | `direction` plus `magnitude` | signed score is derived from direction and magnitude |
| Reason | `rationale` | `analysis.rationale`, signal explanations | `analysis.rationale` is preserved as `rationale` |
| Text echo | `text_chunk` | `current_chunk` is internal only | original `text_chunk` is echoed |
| Timestamp | input timestamp | runtime envelope timestamp | original timestamp is echoed in Redis |
| Session end | `is_session_end` | `is_final` | `is_final` is mapped to `is_session_end` |
| Enrichment | none | signal brief, cards, controls, decision assistant | optional enrichment is additive and ignorable |

## Why This Shape

The original Spring backend expects a simple raw score and performs EMA and rule-engine decisions downstream. The v9 AI engine now has richer strategy, risk, and explanation logic, but pushing that entire shape into the original Redis channel would risk breaking Java consumers.

The compatibility layer therefore uses two outputs:

- `trading-signals`: strict legacy-compatible raw signal
- `trading-signals-enriched`: complete v9 envelope for newer consumers

## Expected Legacy HTTP Response

```json
{
  "ticker": "TSLA",
  "raw_score": -0.62,
  "rationale": "Demand softened and margin pressure increased.",
  "text_chunk": "Margins compressed and demand was softer than expected.",
  "timestamp": 1778600000,
  "is_session_end": false,
  "action": "SELL",
  "confidence": 0.81,
  "strategy": "REVERSAL_CATALYST",
  "hold_days": 2,
  "redis_published": true,
  "enriched_published": true,
  "publish_error": null,
  "engine_envelope": {}
}
```

The response includes `engine_envelope` for debugging and new UI/API clients. Existing data-pipeline callers can ignore the response body if they only rely on Redis.

## Backend Impact

No backend change is required for the original flow:

1. Data pipeline posts STT chunks to `/api/v1/analyze`.
2. AI engine computes the v9 signal internally.
3. AI engine publishes a raw signal to Redis channel `trading-signals`.
4. Spring backend reads the same required fields as before.
5. Frontend and trading terminal receive downstream backend messages unchanged.

## New Dependencies

The AI engine now declares:

```text
redis>=5.0.0,<7.0
```

The publisher still degrades if the Redis package or Redis server is unavailable.
