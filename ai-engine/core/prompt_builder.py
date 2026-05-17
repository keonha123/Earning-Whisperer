from __future__ import annotations

import os

try:
    from config import get_settings
    from models.request_models import MarketData
    from core.token_budgeter import estimate_tokens
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from ..models.request_models import MarketData
    from .token_budgeter import estimate_tokens


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    words = (text or "").split()
    if estimate_tokens(text) <= max_tokens:
        return text
    truncated = words[:]
    while truncated and estimate_tokens(" ".join(truncated)) > max_tokens:
        truncated.pop()
    return " ".join(truncated)


def _truncate_chars(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars]


def _compact_context(context_chunks: list[str], *, budget_tokens: int, max_chunks: int, chunk_chars: int) -> str:
    if budget_tokens <= 0 or not context_chunks:
        return ""
    normalized: list[tuple[int | None, str]] = []
    for chunk in context_chunks:
        seq = getattr(chunk, "sequence", None)
        text = str(getattr(chunk, "text_chunk", chunk)).strip()
        if text:
            normalized.append((seq, text))
    if not normalized:
        return ""

    selected = normalized[-max_chunks:]
    omitted = len(normalized) - len(selected)
    clipped_any = omitted > 0
    pieces: list[str] = []
    used = 0
    for seq, chunk in selected:
        clipped = _truncate_chars(chunk, chunk_chars)
        if len(clipped) < len(chunk):
            clipped_any = True
        label = f"[Chunk {seq}] " if seq is not None else ""
        piece = f"{label}{clipped}"
        cost = len(piece.split()) + 4
        if used + cost > budget_tokens:
            break
        pieces.append(piece)
        used += cost
    if clipped_any:
        pieces.insert(0, "Context compacted for token budget.")
    if omitted > 0:
        pieces.insert(1 if clipped_any else 0, f"[{omitted} older chunk(s) omitted]")
    return "\n---\n".join(pieces)


def build_analysis_prompt(chunk_text: str, market_data: MarketData, max_tokens: int = 600) -> str:
    return build_prompt(
        ticker="UNKNOWN",
        current_chunk=chunk_text,
        context_chunks=[],
        market_data=market_data,
        section_type="OTHER",
        source_type="UNKNOWN",
        prompt_profile="economy",
        context_policy="delta",
        phase1_score=0.0,
        max_tokens=max_tokens,
    )


def build_prompt(
    *,
    ticker: str,
    current_chunk: str,
    context_chunks: list[str],
    market_data: MarketData,
    section_type: str = "OTHER",
    source_type: str | None = None,
    prompt_profile: str | None = None,
    route_profile: str | None = None,
    context_policy: str = "delta",
    phase1_score: float = 0.0,
    max_tokens: int | None = None,
    feature_bundle_context: str | None = None,
) -> str:
    settings = get_settings()
    effective_prompt_profile = prompt_profile or route_profile or "standard"
    profile_budget = {
        "economy": settings.analysis_prompt_budget_economy,
        "standard": settings.analysis_prompt_budget_standard,
        "review": settings.analysis_prompt_budget_review,
    }.get(effective_prompt_profile, settings.analysis_prompt_budget_standard)
    hard_cap = int(os.getenv("ANALYSIS_MAX_PROMPT_TOKENS", os.getenv("GEMINI_MAX_TOKENS", "4096")))
    ceiling = max_tokens or min(int(profile_budget), hard_cap)
    context_limit = int(os.getenv("ANALYSIS_CONTEXT_TOKEN_BUDGET", os.getenv("PROMPT_CONTEXT_MAX_TOKENS", "220")))
    max_chunks = int(os.getenv("ANALYSIS_CONTEXT_MAX_CHUNKS", "4"))
    context_chunk_chars = int(os.getenv("ANALYSIS_CONTEXT_CHUNK_CHARS", "220"))
    current_chunk_chars = int(os.getenv("ANALYSIS_CURRENT_CHUNK_CHARS", "700"))

    extra = "Focus on concise evidence only.\n" if effective_prompt_profile == "economy" else "Use richer reasoning, reconcile current chunk with rolling context, and explain any tension between guidance, demand, margins, and risk factors.\n"
    schema = 'SCHEMA: {"direction": "BULLISH|BEARISH|NEUTRAL", "magnitude": number, "confidence": number, "rationale": string, "catalyst_type": string}\n'
    header = (
        f"TICKER: {ticker}\n"
        f"PROFILE: {effective_prompt_profile}\n"
        f"SECTION: {section_type}\n"
        f"SOURCE_TYPE: {source_type or 'UNKNOWN'}\n"
        f"CONTEXT_POLICY: {context_policy}\n"
        f"PHASE1_SCORE: {phase1_score:.4f}\n"
        f"MARKET_DATA: price={market_data.current_price}, change_pct={market_data.day_change_pct}, volume_ratio={market_data.volume_ratio}, "
        f"vix={market_data.vix}, gap_pct={market_data.gap_pct}, surprise_pct={market_data.surprise_pct}, iv_rank={market_data.iv_rank}\n"
        "INSTRUCTIONS: Return concise JSON with direction, magnitude, confidence, rationale, catalyst_type.\n"
        + schema
        + extra
    )

    if context_policy == "rolling":
        context_text = _compact_context(context_chunks, budget_tokens=context_limit, max_chunks=max_chunks, chunk_chars=context_chunk_chars)
    else:
        latest = context_chunks[-1:] if context_chunks else []
        context_text = _compact_context(latest, budget_tokens=max(40, context_limit // 2), max_chunks=1, chunk_chars=context_chunk_chars)

    current_text = _truncate_chars(current_chunk, current_chunk_chars)
    prompt = f"{header}"
    if context_text:
        prompt += f"CONTEXT_CHUNKS:\n{context_text}\n\n"
    if feature_bundle_context:
        prompt += f"FEATURE_BUNDLE:\n{_truncate_chars(feature_bundle_context, 320)}\n\n"
    prompt += f"CURRENT_CHUNK:\n{current_text}"
    return _truncate_to_tokens(prompt, ceiling)
