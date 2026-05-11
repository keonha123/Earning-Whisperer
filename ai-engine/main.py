"""FastAPI application entrypoint for the upgraded AI engine."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.analyze_router import init_dependencies, router as analyze_router
from api.integration_router import (
    init_dependencies as init_integration_dependencies,
    router as integration_router,
)
from api.research_router import router as research_router
from config import get_settings
from core.analysis_service import analysis_service
from core.context_manager import ContextManager
from core.external_retriever import external_retriever
from core.five_gate_filter import FiveGateFilter
from core.gemini_client import gemini_client
from core.integration_state import IntegrationStateStore
from core.phase1_scorer import phase1_scorer
from core.redis_publisher import RedisPublisher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create shared services for the FastAPI app lifecycle."""

    settings = get_settings()
    logger.info("Starting EarningWhisperer AI Engine v%s", settings.app_version)

    ctx_manager = ContextManager(
        history_size=settings.context_history_size,
        session_ttl=settings.context_session_ttl_seconds,
    )
    gate_filter = FiveGateFilter()
    integration_state = IntegrationStateStore()
    redis_pub = RedisPublisher()

    await redis_pub.connect()
    if settings.phase1_warmup_on_startup:
        await asyncio.to_thread(phase1_scorer.warmup)
    init_dependencies(ctx_manager, gate_filter, redis_pub, integration_state)
    init_integration_dependencies(integration_state)

    cleanup_task = asyncio.create_task(_cleanup_loop(ctx_manager))

    app.state.context_manager = ctx_manager
    app.state.gemini_client = gemini_client
    app.state.gate_filter = gate_filter
    app.state.integration_state = integration_state
    app.state.redis_publisher = redis_pub

    try:
        yield
    finally:
        cleanup_task.cancel()
        await redis_pub.disconnect()
        logger.info("Stopping EarningWhisperer AI Engine")


async def _cleanup_loop(ctx_manager: ContextManager) -> None:
    """Periodically remove expired ticker sessions."""

    while True:
        try:
            await asyncio.sleep(600)
            cleaned = await ctx_manager.cleanup_expired()
            if cleaned > 0:
                logger.info("Cleaned %d expired sessions", cleaned)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Session cleanup failed: %s", exc)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="EarningWhisperer AI Engine",
        description="Real-time earnings-call analysis and trading-signal engine.",
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.include_router(analyze_router)
    app.include_router(integration_router)
    app.include_router(research_router)

    @app.get("/health", tags=["monitoring"])
    async def health():
        retriever_stats = external_retriever.get_stats()
        return {
            "status": "ok",
            "model": settings.gemini_primary_model,
            "primary_model": settings.gemini_primary_model,
            "review_model": settings.gemini_review_model,
            "vector_store_backend": retriever_stats["effective_backend"],
            "version": settings.app_version,
        }

    @app.get("/stats", tags=["monitoring"])
    async def stats():
        gemini_stats = await app.state.gemini_client.get_stats()
        analysis_stats = await analysis_service.get_stats()
        gate_pass_rates = app.state.gate_filter.get_pass_rates()
        active_tickers = await app.state.context_manager.get_active_tickers()
        retriever_stats = external_retriever.get_stats()
        return {
            "active_tickers": active_tickers,
            "gemini_stats": gemini_stats,
            "route_counts": analysis_stats["route_counts"],
            "flash_only_rate": analysis_stats["flash_only_rate"],
            "pro_escalation_rate": analysis_stats["pro_escalation_rate"],
            "avg_estimated_prompt_tokens": analysis_stats["avg_estimated_prompt_tokens"],
            "avg_estimated_output_tokens": analysis_stats["avg_estimated_output_tokens"],
            "economy_prompt_rate": analysis_stats["economy_prompt_rate"],
            "phase1_status": phase1_scorer.status_snapshot(),
            "gate_pass_rates": gate_pass_rates,
            "external_retriever": retriever_stats,
            "redis_connected": app.state.redis_publisher.is_connected,
            "redis_backup_queue": app.state.redis_publisher.backup_queue_size,
            "integration_state_ready": app.state.integration_state is not None,
        }

    return app


app = create_app()
