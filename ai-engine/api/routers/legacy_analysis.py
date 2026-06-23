"""Legacy-compatible analysis endpoint for the original GitHub stack."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

try:
    from api.dependencies import get_dispatch_analysis, get_redis_signal_publisher
    from models.legacy_contract_models import LegacyAnalyzeRequest, LegacyAnalyzeResponse
    from services.legacy_contract_adapter import LegacyContractAdapter
except ImportError:  # pragma: no cover
    from ..dependencies import get_dispatch_analysis, get_redis_signal_publisher
    from ...models.legacy_contract_models import LegacyAnalyzeRequest, LegacyAnalyzeResponse
    from ...services.legacy_contract_adapter import LegacyContractAdapter


router = APIRouter(tags=["legacy-analysis"])


@router.post("/api/v1/analyze", response_model=LegacyAnalyzeResponse)
async def analyze_legacy(payload: LegacyAnalyzeRequest, request: Request) -> LegacyAnalyzeResponse:
    dispatcher = get_dispatch_analysis(request.app)
    adapter = LegacyContractAdapter()
    v9_payload = adapter.to_analyze_request(payload)
    envelope = await dispatcher(v9_payload)
    legacy_signal = adapter.to_legacy_signal(payload, envelope)
    enriched_message = adapter.build_enriched_message(legacy_signal, envelope)

    publish_result = await get_redis_signal_publisher(request.app).publish(
        legacy_signal=legacy_signal,
        enriched_message=enriched_message,
    )
    response: dict[str, Any] = legacy_signal.model_dump(mode="json", exclude_none=True)
    response.update(
        {
            "redis_published": publish_result.legacy_published,
            "enriched_published": publish_result.enriched_published,
            "profile_published": publish_result.profile_published,
            "profile_channel": publish_result.profile_channel,
            "retry_queued": publish_result.retry_queued,
            "publish_error": publish_result.error,
            "engine_envelope": envelope,
        }
    )
    return LegacyAnalyzeResponse.model_validate(response)


__all__ = ["router"]
