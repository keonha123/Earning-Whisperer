# Real Gemini and embedding smoke

`tools/live_gemini_smoke.py` exercises the real translation and grounded QA service classes with a synthetic earnings statement. It also calls the configured transcript/external embedding providers using a three-string related-versus-unrelated fixture. No provider is mocked; hash embeddings cannot pass this verification.

This is a **provider/component smoke**, not audio-to-UI verification. It does not start FastAPI, ingest audio, run STT, visit the terminal, use a production evidence corpus, or connect to Qdrant/Redis/Postgres. Those require a separate end-to-end run. A passing fixture does not establish general financial or translation accuracy.

From `ai-engine`, with Python 3.11+ and project dependencies installed:

```sh
python tools/live_gemini_smoke.py --preflight --output artifacts/provider-preflight.json
```

Preflight is the default and never makes a provider request. The script reads environment variables only unless `--env-file /explicit/path/to/.env` is supplied. It reports missing credential **names**, never credential values. Exit code `2` means unavailable/configuration incomplete; it must not be reported as a passing live test.

Required configuration:

- `GEMINI_API_KEY` and `GEMINI_PRIMARY_MODEL` for translation and the two-stage QA check.
- `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, and optionally `EMBEDDING_VERSION` for transcript embeddings. Provider must be `gemini` or `openai`.
- `EXTERNAL_EMBEDDING_*` selects the external embedding configuration. Empty provider/model/dimension follow the application's normal global fallback. Its version may differ even when the model is identical.
- `OPENAI_API_KEY` is additionally required when either embedding provider is OpenAI. Relevant SDKs must be installed.

To make actual provider requests after configuring authorized credentials:

```sh
python tools/live_gemini_smoke.py --run --env-file .env --output artifacts/provider-live.json
```

The run is small: one translation request, up to two QA generation requests, and one three-text embedding batch for each distinct configured embedding configuration. The normal embedding adapter may retry transient failures. Each phase runs in a separate process; the default hard process deadline is 30 seconds (`--phase-timeout`, range 1–60). Normal service timeouts still apply inside that bound. A killed SDK process cannot continue retrying, although a request already accepted by the provider may still be billed.

The report includes configured model/provider identifiers, translation text, answer/citation results, embedding dimensions and similarity scores, timings, and fixed failure categories. Raw exception messages, SDK logs, credentials, and full embeddings are not forwarded. SDK workers use an isolated temporary working directory so an accidental local `.env` cannot override the explicitly selected settings. Synthetic content is the only content sent.

Exit codes: `0` = preflight ready or actual run passed (check `mode` and `status`), `1` = live phase failed/timed out, `2` = unavailable before attempting paid requests. `available:false`, missing citations, default model fallback, numeric/terminology rejection, invalid vectors, and failed similarity ordering all fail the live run. Reports should be inspected; failures must not be hidden by increasing timeouts or weakening validation merely to obtain a green result.
