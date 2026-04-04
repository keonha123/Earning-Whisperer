"""Cost-aware Gemini routing helpers for live transcript analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..config import get_settings
from ..models.request_models import MarketData, SectionType
from .context_manager import ChunkRecord
from .token_budgeter import estimate_tokens


@dataclass(frozen=True)
class RouteDecision:
    route_profile: str
    context_policy: str
    primary_model: str
    review_model: str
    primary_max_output_tokens: int
    review_max_output_tokens: int
    primary_thinking_level: str
    review_thinking_level: str
    novelty_score: float
    overlap_ratio: float
    estimated_prompt_tokens: int
    important_chunk: bool


def decide_route(
    *,
    current_chunk: str,
    context_chunks: Sequence[ChunkRecord],
    market_data: MarketData | None,
    section_type: SectionType | None,
    request_priority: int,
    is_final: bool,
    phase1_raw_score: float,
) -> RouteDecision:
    """Pick the live primary/review route without skipping LLM calls."""

    settings = get_settings()
    overlap_ratio = normalized_overlap_ratio(
        context_chunks[-1].text_chunk if context_chunks else "",
        current_chunk,
    )
    novelty_score = round(max(0.0, 1.0 - overlap_ratio), 4)

    important_chunk = _is_important_chunk(
        section_type=section_type,
        request_priority=request_priority,
        is_final=is_final,
        phase1_raw_score=phase1_raw_score,
        market_data=market_data,
    )

    route_profile = "standard" if important_chunk else "economy"
    context_policy = _select_context_policy(
        important_chunk=important_chunk,
        novelty_score=novelty_score,
    )
    estimated_prompt_tokens = _estimate_prompt_tokens(
        current_chunk=current_chunk,
        context_chunks=context_chunks,
        market_data=market_data,
        route_profile=route_profile,
        context_policy=context_policy,
    )

    return RouteDecision(
        route_profile=route_profile,
        context_policy=context_policy,
        primary_model=settings.gemini_primary_model,
        review_model=settings.gemini_review_model,
        primary_max_output_tokens=(
            settings.gemini_standard_max_output_tokens
            if route_profile == "standard"
            else settings.gemini_primary_max_output_tokens
        ),
        review_max_output_tokens=settings.gemini_review_max_output_tokens,
        primary_thinking_level=(
            settings.gemini_standard_thinking_level
            if route_profile == "standard"
            else settings.gemini_primary_thinking_level
        ),
        review_thinking_level=settings.gemini_review_thinking_level,
        novelty_score=novelty_score,
        overlap_ratio=round(overlap_ratio, 4),
        estimated_prompt_tokens=estimated_prompt_tokens,
        important_chunk=important_chunk,
    )


def normalized_overlap_ratio(previous_text: str, current_text: str) -> float:
    """Estimate sliding-window overlap by suffix/prefix matching."""

    previous = (previous_text or "").strip()
    current = (current_text or "").strip()
    if not previous or not current:
        return 0.0

    overlap = _longest_overlap_length(previous, current)
    return round(overlap / max(len(current), 1), 4)


def trim_transcript_overlap(previous_text: str, current_text: str) -> str:
    """Remove duplicated suffix/prefix overlap from the current chunk."""

    previous = (previous_text or "").strip()
    current = (current_text or "").strip()
    if not previous or not current:
        return current

    overlap = _longest_overlap_length(previous, current)
    trimmed = current[overlap:].strip()
    return trimmed or current


def _longest_overlap_length(previous: str, current: str) -> int:
    """Return the longest current-prefix that matches the previous suffix in linear time."""

    max_overlap = min(len(previous), len(current))
    previous_tail = previous[-max_overlap:]
    combined = current[:max_overlap] + "\0" + previous_tail
    prefix = [0] * len(combined)

    for idx in range(1, len(combined)):
        candidate = prefix[idx - 1]
        while candidate > 0 and combined[idx] != combined[candidate]:
            candidate = prefix[candidate - 1]
        if combined[idx] == combined[candidate]:
            candidate += 1
        prefix[idx] = candidate

    return min(prefix[-1], max_overlap)


def _is_important_chunk(
    *,
    section_type: SectionType | None,
    request_priority: int,
    is_final: bool,
    phase1_raw_score: float,
    market_data: MarketData | None,
) -> bool:
    if section_type == SectionType.Q_AND_A:
        return True

    settings = get_settings()
    if request_priority >= settings.llm_router_high_priority:
        return True
    if is_final:
        return True
    if abs(phase1_raw_score) >= settings.llm_router_high_signal_raw_threshold:
        return True
    if market_data is None:
        return False
    if (market_data.volume_ratio or 0.0) >= 2.5:
        return True
    if abs(market_data.gap_pct or 0.0) >= 3.0:
        return True
    if abs(market_data.earnings_surprise_pct or 0.0) >= 10.0:
        return True
    return False


def _select_context_policy(*, important_chunk: bool, novelty_score: float) -> str:
    """Shrink context on high-overlap chunks without skipping the LLM path."""

    settings = get_settings()
    if novelty_score < settings.llm_router_novelty_threshold:
        return "delta"
    return "rolling" if important_chunk else "delta"


def _estimate_prompt_tokens(
    *,
    current_chunk: str,
    context_chunks: Sequence[ChunkRecord],
    market_data: MarketData | None,
    route_profile: str,
    context_policy: str,
) -> int:
    prompt_parts = [current_chunk]
    if context_policy == "delta" and context_chunks:
        prompt_parts.append(context_chunks[-1].text_chunk)
    elif context_policy == "rolling":
        prompt_parts.extend(chunk.text_chunk for chunk in context_chunks)

    if market_data is not None:
        if route_profile == "economy":
            lite_values = [
                market_data.current_price,
                market_data.price_change_pct,
                market_data.volume_ratio,
                market_data.vix,
                market_data.earnings_surprise_pct,
                market_data.gap_pct,
                market_data.bid_ask_spread_bps,
                market_data.liquidity_score,
            ]
            prompt_parts.extend(str(value) for value in lite_values if value is not None)
        else:
            prompt_parts.append(str(market_data.model_dump(exclude_none=True)))

    return estimate_tokens("\n".join(prompt_parts))
