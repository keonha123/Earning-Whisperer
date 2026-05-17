from __future__ import annotations

from typing import Any

try:
    from models.request_models import MarketData, SectionType, SourceType
    from core.analysis_service import run_analysis
except ImportError:  # pragma: no cover
    from ....models.request_models import MarketData, SectionType, SourceType
    from ....core.analysis_service import run_analysis


async def analysis_node(state: dict[str, Any]) -> dict[str, Any]:
    transcript_chunk = state.get("transcript_chunk", "")
    route_profile = state.get("route_profile")
    market_data = state.get("market_data") or MarketData()
    if isinstance(market_data, dict):
        market_data = MarketData.model_validate(market_data)

    section_type = state.get("section_type") or SectionType.UNKNOWN
    source_type = state.get("source_type") or SourceType.UNKNOWN
    if isinstance(section_type, str):
        section_type = SectionType(section_type) if section_type in SectionType._value2member_map_ else SectionType.UNKNOWN
    if isinstance(source_type, str):
        source_type = SourceType(source_type) if source_type in SourceType._value2member_map_ else SourceType.UNKNOWN

    result = await run_analysis(
        ticker=state.get("ticker") or market_data.ticker or "UNKNOWN",
        current_chunk=transcript_chunk,
        market_data=market_data,
        section_type=section_type,
        source_type=source_type,
        chunk_sequence=int(state.get("chunk_sequence", 0) or 0),
        request_priority=int(state.get("request_priority", 5) or 5),
        is_final=bool(state.get("is_final", False)),
        route_profile=route_profile or ("review" if state.get("review_requested", False) else None),
    )
    analysis = result.model_dump()
    return {"analysis": analysis, "strategy": analysis.get("strategy", "SENTIMENT_ONLY"), "metadata": analysis.get("metadata", {})}
