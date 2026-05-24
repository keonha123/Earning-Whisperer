"""Health and runtime statistics endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

try:
    from api.dependencies import get_analysis_service, get_repository, get_settings
except ImportError:  # pragma: no cover
    from ..dependencies import get_analysis_service, get_repository, get_settings


router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = get_settings(request.app)
    return {
        "status": "ok",
        "primary_model": settings.gemini_primary_model or "",
        "review_model": settings.gemini_review_model or "",
        "models": {
            "primary": settings.gemini_primary_model or "",
            "review": settings.gemini_review_model or "",
        },
    }


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    settings = get_settings(request.app)
    repository = get_repository(request.app)
    ready = True
    detail_messages: list[str] = []
    checks: dict[str, str] = {}
    if settings.gemini_api_key:
        checks["gemini_api_key"] = "configured"
    else:
        ready = False
        checks["gemini_api_key"] = "missing"
        detail_messages.append("GEMINI_API_KEY is not configured")
    try:
        executor = getattr(repository, "executor", None)
        if executor is not None and hasattr(executor, "fetch_one"):
            row = executor.fetch_one("select 1 as ok")
            database_ready = bool(row)
            ready = ready and database_ready
            checks["database"] = "ready" if database_ready else "unavailable"
            if not database_ready:
                detail_messages.append("Database readiness query returned no rows")
        else:
            checks["database"] = "unknown"
    except Exception as exc:
        ready = False
        checks["database"] = "error"
        detail_messages.append(str(exc))
    status_code = 200 if ready else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if ready else "degraded",
            "detail": "ready" if ready else "; ".join(detail_messages),
            "checks": checks,
        },
    )


@router.get("/stats")
async def stats(request: Request) -> dict[str, Any]:
    settings = get_settings(request.app)
    analysis_service = get_analysis_service(request.app)
    llm_counts = dict(analysis_service.route_counts)
    llm_total = max(1, sum(llm_counts.values()))
    llm_rates = {key: value / llm_total for key, value in llm_counts.items()}
    token_stats = analysis_service.token_budgeter.snapshot()
    route_counts = dict(token_stats.get("route_counts", {}))
    route_total = max(1, sum(route_counts.values()))
    route_rates = {key: value / route_total for key, value in route_counts.items()}
    source_health_stats = analysis_service.source_health_telemetry.snapshot()
    signal_data_hub_stats = (
        analysis_service.signal_data_hub.snapshot()
        if hasattr(analysis_service, "signal_data_hub")
        else {
            "total_topics": 0,
            "cache_hit_rate": 0.0,
            "stale_topic_rate": 0.0,
            "coalesced_hit_rate": 0.0,
        }
    )
    return {
        "route_counts": route_counts,
        "route_profile_counts": route_counts,
        "route_profile_rates": route_rates,
        "llm_route_counts": llm_counts,
        "llm_route_rates": llm_rates,
        "flash_only_rate": route_rates.get("economy", 0.0),
        "pro_escalation_rate": route_rates.get("review", 0.0),
        "economy_prompt_rate": route_rates.get("economy", 0.0),
        "models": {
            "fast": settings.gemini_primary_model,
            "review": settings.gemini_review_model,
        },
        "avg_prompt_tokens": token_stats["avg_prompt_tokens"],
        "avg_output_tokens": token_stats["avg_output_tokens"],
        "cache_hit_rate": token_stats["cache_hit_rate"],
        "coalesced_request_rate": token_stats["coalesced_request_rate"],
        "estimated_total_cost_usd": token_stats["estimated_total_cost_usd"],
        "cost_per_approved_signal": token_stats["cost_per_approved_signal"],
        "budget_exceeded_count": token_stats["budget_exceeded_count"],
        "prompt_budgets": token_stats["prompt_budgets"],
        "route_usage": token_stats["route_stats"],
        "canonical_bundle_rate": source_health_stats["canonical_bundle_rate"],
        "source_health_rate": source_health_stats["source_health_rate"],
        "stale_source_rate": source_health_stats["stale_source_rate"],
        "source_health": source_health_stats,
        "signal_data_hub": signal_data_hub_stats,
        "datahub_topic_count": signal_data_hub_stats["total_topics"],
        "datahub_cache_hit_rate": signal_data_hub_stats["cache_hit_rate"],
        "datahub_stale_topic_rate": signal_data_hub_stats["stale_topic_rate"],
        "datahub_coalesced_hit_rate": signal_data_hub_stats["coalesced_hit_rate"],
    }


__all__ = ["router"]
