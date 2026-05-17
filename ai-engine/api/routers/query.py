"""Persistence, replay, and metrics query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

try:
    from api.dependencies import get_repository
    from models.storage_models import (
        AlertEvaluationResponse,
        BootstrapSchemaResponse,
        ControlRecommendationsResponse,
        EventBundleResponse,
        GateTuningResponse,
        MetricsOverviewResponse,
        QualityScorecardResponse,
        ReplayPatchRequest,
        ReplayPatchResponse,
        RunBundleResponse,
        RunListResponse,
        StrategyDriftResponse,
        StrategyLeaderboardResponse,
    )
except ImportError:  # pragma: no cover
    from ..dependencies import get_repository
    from ...models.storage_models import (
        AlertEvaluationResponse,
        BootstrapSchemaResponse,
        ControlRecommendationsResponse,
        EventBundleResponse,
        GateTuningResponse,
        MetricsOverviewResponse,
        QualityScorecardResponse,
        ReplayPatchRequest,
        ReplayPatchResponse,
        RunBundleResponse,
        RunListResponse,
        StrategyDriftResponse,
        StrategyLeaderboardResponse,
    )


router = APIRouter(tags=["query"])


@router.get("/v1/engine/runs", response_model=RunListResponse)
async def list_runs(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    ticker: str | None = None,
    strategy_code: str | None = None,
    status: str | None = None,
) -> RunListResponse:
    repository = get_repository(request.app)
    try:
        result = repository.list_runs(limit=limit, offset=offset, ticker=ticker, strategy_code=strategy_code, status=status)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RunListResponse(status="ok", result=result)


@router.get("/v1/engine/metrics/overview", response_model=MetricsOverviewResponse)
async def get_metrics_overview(request: Request, lookback_days: int = 30) -> MetricsOverviewResponse:
    repository = get_repository(request.app)
    try:
        result = repository.get_metrics_overview(lookback_days=lookback_days)
        active_rollouts = repository.list_rollouts(status="active", limit=100, offset=0) if hasattr(repository, "list_rollouts") else {"items": []}
        control_states = repository.list_control_states(limit=100, offset=0) if hasattr(repository, "list_control_states") else {"items": []}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    suppressed = [
        item
        for item in control_states.get("items", [])
        if item.get("enabled") and item.get("control_type") in {"signal_suppress", "global_kill_switch"}
    ]
    result["rollout_health"] = {
        "active_rollout_count": len(active_rollouts.get("items", [])),
        "items": active_rollouts.get("items", []),
    }
    result["suppressed_signal_rate"] = 1.0 if suppressed else 0.0
    result["control_state_summary"] = {
        "active_control_count": len([item for item in control_states.get("items", []) if item.get("enabled")]),
        "items": control_states.get("items", []),
    }
    return MetricsOverviewResponse(status="ok", result=result)


@router.get("/v1/engine/metrics/scorecard", response_model=QualityScorecardResponse)
async def get_quality_scorecard(request: Request, lookback_days: int = 30) -> QualityScorecardResponse:
    repository = get_repository(request.app)
    try:
        result = repository.get_quality_scorecard(lookback_days=lookback_days)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return QualityScorecardResponse(status="ok", result=result)


@router.get("/v1/engine/metrics/drift", response_model=StrategyDriftResponse)
async def get_strategy_drift(request: Request, short_window_days: int = 7, baseline_window_days: int = 30) -> StrategyDriftResponse:
    repository = get_repository(request.app)
    try:
        result = repository.get_strategy_drift(short_window_days=short_window_days, baseline_window_days=baseline_window_days)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return StrategyDriftResponse(status="ok", result=result)


@router.get("/v1/engine/metrics/leaderboard", response_model=StrategyLeaderboardResponse)
async def get_strategy_leaderboard(
    request: Request,
    lookback_days: int = 30,
    limit: int = 10,
    min_closed: int = 3,
    metric: str = "avg_realized_pnl_pct",
) -> StrategyLeaderboardResponse:
    repository = get_repository(request.app)
    try:
        result = repository.get_strategy_leaderboard(
            lookback_days=lookback_days,
            limit=limit,
            min_closed=min_closed,
            metric=metric,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return StrategyLeaderboardResponse(status="ok", result=result)


@router.get("/v1/engine/controls/recommendations", response_model=ControlRecommendationsResponse)
async def get_control_recommendations(
    request: Request,
    short_window_days: int = 7,
    baseline_window_days: int = 30,
    lookback_days: int = 30,
) -> ControlRecommendationsResponse:
    repository = get_repository(request.app)
    try:
        result = repository.get_control_recommendations(
            short_window_days=short_window_days,
            baseline_window_days=baseline_window_days,
            lookback_days=lookback_days,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ControlRecommendationsResponse(status="ok", result=result)


@router.get("/v1/engine/controls/gate-tuning", response_model=GateTuningResponse)
async def get_gate_tuning_recommendations(
    request: Request,
    short_window_days: int = 7,
    baseline_window_days: int = 30,
    lookback_days: int = 30,
) -> GateTuningResponse:
    repository = get_repository(request.app)
    try:
        result = repository.get_gate_tuning_recommendations(
            short_window_days=short_window_days,
            baseline_window_days=baseline_window_days,
            lookback_days=lookback_days,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateTuningResponse(status="ok", result=result)


@router.get("/v1/engine/alerts/evaluate", response_model=AlertEvaluationResponse)
async def evaluate_alerts(
    request: Request,
    short_window_days: int = 7,
    baseline_window_days: int = 30,
    lookback_days: int = 30,
) -> AlertEvaluationResponse:
    repository = get_repository(request.app)
    try:
        result = repository.evaluate_alerts(
            short_window_days=short_window_days,
            baseline_window_days=baseline_window_days,
            lookback_days=lookback_days,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AlertEvaluationResponse(status="ok", result=result)


@router.get("/v1/engine/runs/{run_id}", response_model=RunBundleResponse)
async def get_run_bundle(run_id: str, request: Request) -> RunBundleResponse:
    repository = get_repository(request.app)
    try:
        bundle = repository.get_run_bundle(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not bundle:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return RunBundleResponse(status="ok", run_id=run_id, bundle=bundle)


@router.get("/v1/engine/events/{event_id}", response_model=EventBundleResponse)
async def get_event_bundle(event_id: str, request: Request) -> EventBundleResponse:
    repository = get_repository(request.app)
    try:
        bundle = repository.get_event_bundle(event_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not bundle:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
    return EventBundleResponse(status="ok", event_id=event_id, bundle=bundle)


@router.patch("/v1/engine/replay/{run_id}", response_model=ReplayPatchResponse)
async def patch_replay_track(run_id: str, payload: ReplayPatchRequest, request: Request) -> ReplayPatchResponse:
    repository = get_repository(request.app)
    patch = payload.model_dump(exclude_unset=True)
    try:
        result = repository.update_replay_track(run_id, patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ReplayPatchResponse(status="ok", updated=result.updated, run_id=result.run_id, fields_updated=result.fields_updated)


@router.post("/v1/engine/admin/bootstrap-schema", response_model=BootstrapSchemaResponse)
async def bootstrap_schema(request: Request) -> BootstrapSchemaResponse:
    repository = get_repository(request.app)
    try:
        result = repository.bootstrap_schema()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Schema file not found: {exc}") from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to bootstrap schema: {exc}") from exc
    return BootstrapSchemaResponse(status="ok", applied=result.applied, schema_path=result.schema_path)


__all__ = ["router"]
