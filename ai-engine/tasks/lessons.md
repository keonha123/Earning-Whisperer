# Lessons

- Keep new API fields additive so existing clients and tests continue to pass.
- Product-grade control paths need persisted evidence and audit records; avoid returning success from placeholder IDs or implicit state.
- Keep the project positioned as `AI engine only`; do not drift into frontend, gateway, auth, payment, or upstream ingestion scope.
- When restructuring, separate API wiring from engine logic first; do not let `main.py` become the product architecture.
- yfinance in this environment may inherit broken proxy settings or unwritable default cache paths; force cache into the workspace and clear proxy env vars for live research runs.
- When references disagree on features, stabilize the product contract first: canonical bundle input, signal brief output, and source-health observability are higher leverage than adding more raw model logic.
- When adding optional feature columns to proxy backtest frames, never end the pipeline with a blanket `dropna()`; fill neutral defaults for optional context and drop only on the execution-critical columns.
- Higher-timeframe indicators like weekly Ichimoku need time-aligned series in backtests; using only the final snapshot leaks future information.
- When tightening conservative tracks, inspect fallback paths as well as primary blockers; a blocked continuation setup that leaks into a weaker fallback strategy can recreate the same drawdown under a different label.
- Large-gap continuation rules need sign awareness: a conservative profile may want to block euphoric upside gaps while still allowing selected downside-dislocation breakouts that recover with confirmation.
- When redesigning aggressive tracks, start from the approved-trade artifact and turn the track into a post-selection subset with explicit regime, sector, and strategy hard blockers; this is more stable than relaxing gate thresholds and hoping event quality will self-filter.
- If an aggressive track needs a few more samples, prefer narrow sector-scoped rotation into the allowed strategy sleeve over global fallback; a broad fallback can restore trade count by flooding low-quality technology names and destroy drawdown.
- App-scoped runtime services must stay app-scoped end to end; do not bypass `app.state` with module-global fallbacks or per-request constructors for contextful components like analysis routing, token telemetry, or rolling chunk memory.
- Database-backed controls must fail fast when PostgreSQL is unavailable; otherwise control-plane lookups can stall analyze requests even if the engine can degrade safely without persistence.
- Repository upsert targets and SQL bootstrap constraints must be reviewed together; an `ON CONFLICT (...)` path without a matching unique or exclusion constraint can pass unit tests and still fail immediately in production PostgreSQL.
- If a product risks looking like retail brokerage AI, add verifiable institutional artifacts: evidence scoring, execution feasibility, capacity/slippage limits, red-team thesis, kill conditions, and replay/control linkage.
- When using external repositories as references, copy architectural ideas only after checking license risk; reimplement the concept in the local architecture instead of importing or pasting source.
- Do not treat canonical bundles or source-health summaries as RAG by themselves; an explicit evidence layer must retrieve cited source/date/confidence snippets and inject only those citations into the LLM prompt.
