"""Operational endpoints for durable Redis signal delivery."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

try:
    from api.dependencies import get_redis_signal_publisher
    from models.intelligence_models import RedisRetryResponse
except ImportError:  # pragma: no cover
    from ..dependencies import get_redis_signal_publisher
    from ...models.intelligence_models import RedisRetryResponse


router = APIRouter(tags=["signal-delivery"])


@router.post("/v1/engine/redis/retry", response_model=RedisRetryResponse)
async def retry_redis_signals(request: Request, limit: int = Query(default=100, ge=1, le=1000)) -> RedisRetryResponse:
    return await get_redis_signal_publisher(request.app).retry_pending(limit=limit)


@router.get("/v1/engine/redis/retry/status")
def redis_retry_status(request: Request) -> dict:
    publisher = get_redis_signal_publisher(request.app)
    return {
        "pending": publisher.retry_spool.count(),
        "spool_path": str(publisher.retry_spool.path),
        "profile_publish_enabled": publisher.settings.redis_profile_publish_enabled,
    }


__all__ = ["router"]
