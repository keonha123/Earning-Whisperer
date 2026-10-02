# Transcript translation and grounded questions

These internal AI-engine routes are additive; they never replace or delay the original transcript stream. Backend callers must authenticate users and resolve selected segments from the stored call. Do not expose the engine directly as an authenticated public API.

## Korean translation

`POST /v1/engine/transcript/translate`

```json
{"ticker":"NVDA","call_id":"call-1","sequence":81,"text":"Revenue grew 20%."}
```

Response keys: `available`, `ticker`, `call_id`, `sequence`, `original_text`, nullable `text_ko`, `warnings`. Keep `(call_id, sequence)` when applying delayed responses; a response for an older call must never overwrite the active call. Missing credentials, timeout, invalid output, changed numbers/units, or a lost negation return `available:false` and no translated text. Original text is always retained.

Latest remote translation producers may omit `call_id` and supply `terms: [{"term":"Revenue","ko":"매출"}]` (up to 50 terms). Translation echoes a nullable call ID and returns `terms_used`; QA continues to require a nonempty call ID. Supplied terms override the local translation glossary for that request; an explicit empty list means no fixed terms. With no `terms` field, matching local terms are used. Duplicate term names are matched case-insensitively, first entry wins, and overlapping Korean text cannot count as two applied terms. Missing required terms fails closed. A backend must not apply an identity-less translation to a live session.

The backend packaged `/api/v1/glossary` contract is additive to `/api/v1/transcript/glossary`, whose richer AI definitions remain available for grounded QA.

Spoken English quantities from zero through nine hundred ninety-nine are compared to equivalent Arabic numerals, including hyphenated tens and `hundred and` phrases. Thus `twenty percent` can translate as `20%`; percentage points remain distinct from percentages. Numeric order, values and magnitude/currency units are still checked. This bounded normalization is not a general number-language parser; unsupported expressions may be withheld for inspection rather than guessed.

Financial numeric notation and English numerical units are intentionally preserved exactly, for example `$5 billion`, rather than converting to Korean units. Numeric token and unit sequences are checked locally, rejecting rearranged quantities conservatively as well as changed quantities. This does not prove semantic accuracy or correct associations between quantities and claims; human/provider validation remains necessary before relying on live translation quality. A curated 41-term glossary guides financial terminology; matching source terms must retain their canonical Korean term in the output. The default model wait limit is 8 seconds; `TRANSCRIPT_TRANSLATION_TIMEOUT_SECONDS` can override it. The HTTP wait is bounded; an already-running provider SDK worker may finish afterward.

`GET /v1/engine/glossary` returns `{version,terms}`. Each term has `term`, `aliases`, `ko`, `definition_ko`, `why_ko`, and `category`. `/v1/engine/transcript/glossary` is an alias. Definitions describe concepts and do not recommend trades.

## Selected-segment questions

`POST /v1/engine/transcript/ask`

```json
{
  "ticker":"NVDA",
  "call_id":"call-1",
  "segment_sequences":[81],
  "segment_texts":["Revenue increased 20% because demand grew."],
  "question":"매출이 증가한 이유는 무엇인가요?",
  "as_of":"2026-01-05T12:00:00Z",
  "context_before":"",
  "context_after":""
}
```

The backend supplies authoritative segment text and an as-of boundary for this call. Lists must have matching lengths, 1–10 unique nonnegative sequences, nonempty text, and at most 16,000 combined text characters. `as_of` must include a timezone. Context is optional and cannot serve as evidence unless separately returned as a selected segment.

An optional `insufficient_reason` (up to 1,000 characters) carries the backend's actual analysis warning. A question asking why evidence is insufficient returns `insufficient` when that reason was not supplied, rather than inventing an explanation. When supplied, the answer must quote that reason as evidence; these system-state questions need not additionally quote a selected segment.

Response keys: `available`, `ticker`, `call_id`, `segment_sequences`, nullable `answer_ko`, `refused`, nullable `refusal_reason`, `evidence`, `citations`, and `warnings`. Citations contain a **zero-based** `evidence_index` and an exact `quote` from that evidence snippet. Segment evidence includes `call_id` and `sequence` metadata. The backend is responsible for resolving this provenance; the engine does not independently query a segment database.

Answers must cite at least one selected segment; external evidence is supplementary. Undated, wrong-ticker, future, and low-relevance external evidence is excluded. A date-only source is conservatively usable only after the entire UTC publication day has elapsed. Scope and direct investment-advice guards run before generation; the model must additionally return a validated verdict. Uncited answers, invalid citation indices, fabricated quotes, and generic model fallback objects are rejected. A second model verification pass must accept the complete answer unchanged; a refusal, altered answer, or timeout withholds the answer while retaining evidence. Both calls share the total deadline. Model decisions and quotation validation reduce unsupported answers but are not a formal entailment proof.

`refusal_reason` can be `investment_advice`, `out_of_scope`, `insufficient`, `model_unavailable`, `timeout`, or `invalid_or_unsupported_response`. Unavailability is not a policy refusal: `refused` is true only for advice/scope. No-evidence/model-timeout/invalid-answer states keep the evidence list for inspection. The default total QA wait budget is 25 seconds, with retrieval capped at 4 seconds and half the total budget. `TRANSCRIPT_QA_TIMEOUT_SECONDS` can override it. Questions are single-turn; no hidden conversation memory is used.

## Verification

`py -3.13 -m pytest tests/test_transcript_assistant.py -q`

These tests use deterministic fake model responses and cover identities, numeric/unit/negation failures, missing keys, timeouts, policy refusals, exact citations, temporal/ticker isolation, malformed responses, glossary completeness and input contracts. They do not establish real Gemini linguistic quality, latency, or production credential readiness.

### Grounded prior-call and terminology answers

Questions explicitly asking about the previous call or quarter retrieve the latest dated transcript strictly before the selected segment timestamp. The current call is excluded when its document ID or stored call ID matches; at most three decreasing-date lookups are attempted. Only same-ticker chunks from that exact prior document are accepted. Missing, unavailable, undated or irrelevant prior evidence returns `insufficient` with `prior_transcript_unavailable`; a comparison must cite both a selected segment and the prior transcript. Retrieval and both model passes share the configured overall QA deadline.

Explicit terminology questions add matching curated definitions as `curated_glossary` evidence. Definitions require an exact glossary quotation in addition to the selected segment citation. Longest non-overlapping term matching prevents `non-GAAP` from also requiring the unrelated `GAAP` expansion and `diluted EPS` from requiring two translations. Explicit foreign `$SYMBOL` or `ticker: SYMBOL` questions are rejected before model use; financial acronyms without ticker notation are left to the normal grounded scope checks.
