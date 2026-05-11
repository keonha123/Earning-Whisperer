"""Prompt construction utilities for Gemini live routing profiles."""

from __future__ import annotations

import json
from typing import Sequence

from config import get_settings
from models.request_models import MarketData
from models.signal_models import GeminiAnalysisResult
from .context_manager import ChunkRecord
from .external_retriever import ExternalRetrievedDocument
from .llm_router import trim_transcript_overlap

SYSTEM_PROMPT = """You are the earnings-call analysis engine for EarningWhisperer.

You must return JSON only with these fields:
- cot_reasoning
- direction
- magnitude
- confidence
- rationale
- catalyst_type
- euphemism_count
- negative_word_ratio

Rules:
- direction must be BULLISH, BEARISH, or NEUTRAL
- catalyst_type must be one of:
  EARNINGS_BEAT, EARNINGS_MISS, GUIDANCE_UP, GUIDANCE_DOWN, GUIDANCE_HOLD,
  RESTRUCTURING, PRODUCT_NEWS, MACRO_COMMENTARY, REGULATORY_RISK, OPERATIONAL_EXEC
- rationale must be grounded in the supplied text and market data only
- cot_reasoning must be concise and factual
- never output markdown, code fences, or extra prose
"""


def build_prompt(
    *,
    ticker: str,
    current_chunk: str,
    context_chunks: Sequence[ChunkRecord],
    market_data: MarketData | None,
    prompt_profile: str = "standard",
    context_policy: str = "rolling",
    phase1_score: float | None = None,
    previous_result: GeminiAnalysisResult | None = None,
    review_reason: str | None = None,
    external_docs: Sequence[ExternalRetrievedDocument] | None = None,
    external_query: str | None = None,
) -> str:
    """Build a prompt for the selected route profile and context policy."""

    header = [
        f"Ticker: {ticker}",
        f"Prompt profile: {prompt_profile}",
        _profile_instruction(prompt_profile),
    ]
    sections: list[str] = ["\n".join(header)]

    context_block = _build_context_block(
        current_chunk=current_chunk,
        context_chunks=context_chunks,
        context_policy=context_policy,
    )
    if context_block:
        sections.append(context_block)

    market_block = _build_market_block(market_data, prompt_profile)
    if market_block:
        sections.append(market_block)

    retrieval_block = _build_external_evidence_block(
        external_docs=external_docs or [],
        external_query=external_query,
    )
    if retrieval_block:
        sections.append(retrieval_block)

    if context_policy == "adjudication":
        sections.append(
            _build_review_block(
                phase1_score=phase1_score,
                previous_result=previous_result,
                review_reason=review_reason,
            )
        )

    sections.append(_output_contract(prompt_profile))
    return "\n\n".join(part for part in sections if part)


def _build_context_block(
    *,
    current_chunk: str,
    context_chunks: Sequence[ChunkRecord],
    context_policy: str,
) -> str:
    previous_text = context_chunks[-1].text_chunk if context_chunks else ""

    if context_policy == "delta":
        trimmed = trim_transcript_overlap(previous_text, current_chunk)
        parts = ["## Transcript chunk", trimmed]
        if previous_text:
            parts.extend(["## Anchor context", previous_text])
        return "\n".join(parts)

    if context_policy == "adjudication":
        parts = ["## Transcript chunk", current_chunk]
        if previous_text:
            parts.extend(["## Anchor context", previous_text])
        return "\n".join(parts)

    rolling = "\n".join(
        f"[Chunk {record.sequence}] {record.text_chunk}" for record in context_chunks
    )
    parts = []
    if rolling:
        parts.extend(["## Rolling context", rolling])
    parts.extend(["## Transcript chunk", current_chunk])
    return "\n".join(parts)


def _build_market_block(market_data: MarketData | None, prompt_profile: str) -> str:
    if market_data is None:
        return ""

    if prompt_profile == "economy":
        payload = {
            "current_price": market_data.current_price,
            "price_change_pct": market_data.price_change_pct,
            "volume_ratio": market_data.volume_ratio,
            "vix": market_data.vix,
            "earnings_surprise_pct": market_data.earnings_surprise_pct,
            "gap_pct": market_data.gap_pct,
            "bid_ask_spread_bps": market_data.bid_ask_spread_bps,
            "liquidity_score": market_data.liquidity_score,
        }
    else:
        payload = market_data.model_dump(exclude_none=True)

    payload = {key: value for key, value in payload.items() if value is not None}
    if not payload:
        return ""
    return "## Market data\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _build_review_block(
    *,
    phase1_score: float | None,
    previous_result: GeminiAnalysisResult | None,
    review_reason: str | None,
) -> str:
    result_payload = previous_result.model_dump(exclude_none=True) if previous_result else {}
    lines = [
        "## Review task",
        "Re-evaluate the first-pass output and return the corrected final JSON only.",
    ]
    if review_reason:
        lines.append(f"Review reason: {review_reason}")
    if phase1_score is not None:
        lines.append(f"Phase-1 raw score: {phase1_score:.4f}")
    if result_payload:
        lines.append(
            "First-pass result: "
            + json.dumps(result_payload, ensure_ascii=False, separators=(",", ":"))
        )
    return "\n".join(lines)


def _build_external_evidence_block(
    *,
    external_docs: Sequence[ExternalRetrievedDocument],
    external_query: str | None,
) -> str:
    if not external_docs:
        return ""

    settings = get_settings()
    lines = ["## External evidence"]
    if external_query:
        lines.append(f"External query: {external_query}")
    for doc in external_docs:
        text = doc.text.strip()
        if len(text) > settings.rag_context_chars_per_doc:
            text = text[: settings.rag_context_chars_per_doc - 3].rstrip() + "..."
        header = f"[{doc.source_type} | {doc.published_at} | score={doc.score:.2f}]"
        if doc.form_type:
            header = f"{header} {doc.form_type}"
        if doc.title:
            header = f"{header} {doc.title}"
        lines.append(header)
        lines.append(text)
        if doc.url:
            lines.append(f"URL: {doc.url}")
    return "\n".join(lines)


def _profile_instruction(prompt_profile: str) -> str:
    if prompt_profile == "economy":
        return (
            "Return a short one-sentence rationale and keep cot_reasoning brief. "
            "Focus on the dominant directional evidence only."
        )
    if prompt_profile == "adjudication":
        return (
            "Resolve ambiguity from the first pass. Keep rationale to two sentences max "
            "and correct any direction, confidence, or catalyst mistakes."
        )
    return (
        "Return a concise two-sentence rationale grounded in the most material evidence. "
        "Use the full rolling context when it changes the interpretation."
    )


def _output_contract(prompt_profile: str) -> str:
    rationale_hint = (
        "1 sentence max" if prompt_profile == "economy" else "2 sentences max"
    )
    cot_hint = "short and compact" if prompt_profile == "economy" else "concise but explicit"
    return (
        "## Output contract\n"
        "{\n"
        '  "cot_reasoning": "<' + cot_hint + '>",\n'
        '  "direction": "BULLISH|BEARISH|NEUTRAL",\n'
        '  "magnitude": 0.0,\n'
        '  "confidence": 0.0,\n'
        '  "rationale": "<' + rationale_hint + '>",\n'
        '  "catalyst_type": "EARNINGS_BEAT",\n'
        '  "euphemism_count": 0,\n'
        '  "negative_word_ratio": 0.0\n'
        "}"
    )
