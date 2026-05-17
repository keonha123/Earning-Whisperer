from __future__ import annotations

from dataclasses import dataclass

try:
    from config import get_settings
    from models.request_models import MarketData, SectionType
    from core.context_manager import ChunkRecord, novelty_against_context
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from ..models.request_models import MarketData, SectionType
    from .context_manager import ChunkRecord, novelty_against_context


@dataclass(slots=True)
class RouteDecision:
    route_profile: str
    context_policy: str
    max_output_tokens: int
    thinking_level: str
    model: str
    novelty: float

    @property
    def primary_model(self) -> str:
        return self.model


def decide_route(
    *,
    current_chunk: str,
    context_chunks: list[ChunkRecord],
    market_data: MarketData,
    section_type: SectionType,
    request_priority: int,
    is_final: bool,
    phase1_raw_score: float,
) -> RouteDecision:
    settings = get_settings()
    novelty = novelty_against_context(current_chunk, context_chunks)
    high_signal = abs(phase1_raw_score) >= settings.llm_router_high_signal_raw_threshold
    high_priority = request_priority >= settings.llm_router_high_priority
    qna_bias = section_type == SectionType.Q_AND_A

    if qna_bias and not context_chunks:
        context_policy = "rolling"
    elif not context_chunks:
        context_policy = "delta"
    else:
        context_policy = "delta" if novelty < settings.llm_router_novelty_threshold else "rolling"

    if is_final and (high_priority or high_signal or qna_bias):
        route_profile = "review"
        max_output_tokens = settings.gemini_review_max_output_tokens
        thinking_level = settings.gemini_review_thinking_level
        model = settings.gemini_review_model or settings.gemini_primary_model or settings.gemini_model_fast
    elif high_signal or high_priority or qna_bias:
        route_profile = "standard"
        max_output_tokens = settings.gemini_standard_max_output_tokens
        thinking_level = settings.gemini_standard_thinking_level
        model = settings.gemini_primary_model or settings.gemini_model_fast
    else:
        route_profile = "economy"
        max_output_tokens = settings.gemini_primary_max_output_tokens
        thinking_level = settings.gemini_primary_thinking_level
        model = settings.gemini_primary_model or settings.gemini_model_fast

    return RouteDecision(
        route_profile=route_profile,
        context_policy=context_policy,
        max_output_tokens=max_output_tokens,
        thinking_level=thinking_level,
        model=model,
        novelty=novelty,
    )
