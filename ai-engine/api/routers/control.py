"""Control plane and rollout endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

try:
    from api.dependencies import get_control_service, get_repository
    from models.storage_models import (
        ActiveGateConfigListResponse,
        AlertStateListResponse,
        AlertStateUpsertRequest,
        AlertStateUpsertResponse,
        EmergencyStateResponse,
        EmergencyStateUpsertRequest,
        GateAutoPromotionRequest,
        GateAutoPromotionResponse,
        GateConfigRollbackRequest,
        GateConfigRollbackResponse,
        GatePatchApplyRequest,
        GatePatchApplyResponse,
        GatePatchAuditResponse,
        GatePatchDecisionRequest,
        GatePatchDecisionResponse,
        GatePatchListResponse,
        GatePatchUpsertRequest,
        GatePatchUpsertResponse,
        GateRolloutActionRequest,
        GateRolloutCreateRequest,
        GateRolloutListResponse,
        GateRolloutResponse,
        GateShadowCompareRequest,
        GateShadowCompareResponse,
    )
except ImportError:  # pragma: no cover
    from ..dependencies import get_control_service, get_repository
    from ...models.storage_models import (
        ActiveGateConfigListResponse,
        AlertStateListResponse,
        AlertStateUpsertRequest,
        AlertStateUpsertResponse,
        EmergencyStateResponse,
        EmergencyStateUpsertRequest,
        GateAutoPromotionRequest,
        GateAutoPromotionResponse,
        GateConfigRollbackRequest,
        GateConfigRollbackResponse,
        GatePatchApplyRequest,
        GatePatchApplyResponse,
        GatePatchAuditResponse,
        GatePatchDecisionRequest,
        GatePatchDecisionResponse,
        GatePatchListResponse,
        GatePatchUpsertRequest,
        GatePatchUpsertResponse,
        GateRolloutActionRequest,
        GateRolloutCreateRequest,
        GateRolloutListResponse,
        GateRolloutResponse,
        GateShadowCompareRequest,
        GateShadowCompareResponse,
    )


router = APIRouter(tags=["control"])


@router.post("/v1/engine/controls/gate-patches", response_model=GatePatchUpsertResponse)
async def create_gate_patch(payload: GatePatchUpsertRequest, request: Request) -> GatePatchUpsertResponse:
    repository = get_repository(request.app)
    try:
        result = repository.save_gate_patch(payload.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GatePatchUpsertResponse(status="ok", result=result)


@router.get("/v1/engine/controls/gate-patches", response_model=GatePatchListResponse)
async def list_gate_patches(
    request: Request,
    strategy_code: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> GatePatchListResponse:
    repository = get_repository(request.app)
    try:
        result = repository.list_gate_patches(strategy_code=strategy_code, status=status, limit=limit, offset=offset)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GatePatchListResponse(status="ok", result=result)


@router.post("/v1/engine/controls/gate-patches/{patch_id}/approve", response_model=GatePatchDecisionResponse)
async def approve_gate_patch(patch_id: int, payload: GatePatchDecisionRequest, request: Request) -> GatePatchDecisionResponse:
    try:
        result = get_control_service(request.app).approve_patch(patch_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GatePatchDecisionResponse(status="ok", result=result)


@router.post("/v1/engine/controls/gate-patches/{patch_id}/reject", response_model=GatePatchDecisionResponse)
async def reject_gate_patch(patch_id: int, payload: GatePatchDecisionRequest, request: Request) -> GatePatchDecisionResponse:
    try:
        result = get_control_service(request.app).reject_patch(patch_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GatePatchDecisionResponse(status="ok", result=result)


@router.get("/v1/engine/controls/gate-patches/{patch_id}/audit", response_model=GatePatchAuditResponse)
async def get_gate_patch_audit(patch_id: int, request: Request) -> GatePatchAuditResponse:
    try:
        result = get_control_service(request.app).get_patch_audit(patch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GatePatchAuditResponse(status="ok", result=result)


@router.post("/v1/engine/controls/gate-patches/{patch_id}/rollouts", response_model=GateRolloutResponse)
async def create_rollout(patch_id: int, payload: GateRolloutCreateRequest, request: Request) -> GateRolloutResponse:
    try:
        result = get_control_service(request.app).start_rollout(patch_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateRolloutResponse(status="ok", result=result)


@router.post("/v1/engine/alerts/state-actions", response_model=AlertStateUpsertResponse)
async def create_alert_state_action(payload: AlertStateUpsertRequest, request: Request) -> AlertStateUpsertResponse:
    repository = get_repository(request.app)
    try:
        result = repository.save_alert_state_action(payload.model_dump(mode="json"))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AlertStateUpsertResponse(status="ok", result=result)


@router.get("/v1/engine/alerts/state-actions", response_model=AlertStateListResponse)
async def list_alert_state_actions(
    request: Request,
    code: str | None = None,
    scope: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> AlertStateListResponse:
    repository = get_repository(request.app)
    try:
        result = repository.list_alert_state_actions(code=code, scope=scope, limit=limit, offset=offset)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AlertStateListResponse(status="ok", result=result)


@router.post("/v1/engine/controls/gate-patches/{patch_id}/apply", response_model=GatePatchApplyResponse)
async def apply_gate_patch(patch_id: int, payload: GatePatchApplyRequest, request: Request) -> GatePatchApplyResponse:
    repository = get_repository(request.app)
    try:
        result = repository.apply_gate_patch(patch_id, actor=payload.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GatePatchApplyResponse(status="ok", result=result)


@router.get("/v1/engine/controls/gate-configs", response_model=ActiveGateConfigListResponse)
async def list_active_gate_configs(request: Request, strategy_code: str | None = None, limit: int = 20, offset: int = 0) -> ActiveGateConfigListResponse:
    repository = get_repository(request.app)
    try:
        result = repository.list_active_gate_configs(strategy_code=strategy_code, limit=limit, offset=offset)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ActiveGateConfigListResponse(status="ok", result=result)


@router.post("/v1/engine/controls/gate-configs/{strategy_code}/rollback", response_model=GateConfigRollbackResponse)
async def rollback_gate_config(strategy_code: str, payload: GateConfigRollbackRequest, request: Request) -> GateConfigRollbackResponse:
    repository = get_repository(request.app)
    try:
        result = repository.rollback_active_gate_config(strategy_code, target_patch_id=payload.target_patch_id, actor=payload.actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateConfigRollbackResponse(status="ok", result=result)


@router.get("/v1/engine/controls/rollouts", response_model=GateRolloutListResponse)
async def list_rollouts(request: Request, strategy_code: str | None = None, status: str | None = None, limit: int = 20, offset: int = 0) -> GateRolloutListResponse:
    try:
        result = get_control_service(request.app).list_rollouts(strategy_code=strategy_code, status=status, limit=limit, offset=offset)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateRolloutListResponse(status="ok", result=result)


@router.get("/v1/engine/controls/rollouts/{rollout_id}", response_model=GateRolloutResponse)
async def get_rollout(rollout_id: int, request: Request) -> GateRolloutResponse:
    try:
        result = get_control_service(request.app).get_rollout(rollout_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateRolloutResponse(status="ok", result=result)


@router.post("/v1/engine/controls/rollouts/{rollout_id}/advance", response_model=GateRolloutResponse)
async def advance_rollout(rollout_id: int, payload: GateRolloutActionRequest, request: Request) -> GateRolloutResponse:
    try:
        result = get_control_service(request.app).advance_rollout(rollout_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateRolloutResponse(status="ok", result=result)


@router.post("/v1/engine/controls/rollouts/{rollout_id}/abort", response_model=GateRolloutResponse)
async def abort_rollout(rollout_id: int, payload: GateRolloutActionRequest, request: Request) -> GateRolloutResponse:
    try:
        result = get_control_service(request.app).abort_rollout(rollout_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateRolloutResponse(status="ok", result=result)


@router.get("/v1/engine/controls/emergency-state", response_model=EmergencyStateResponse)
async def get_emergency_state(
    request: Request,
    control_type: str | None = None,
    scope_type: str | None = None,
    scope_key: str | None = None,
) -> EmergencyStateResponse:
    try:
        result = get_control_service(request.app).get_emergency_state(control_type=control_type, scope_type=scope_type, scope_key=scope_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return EmergencyStateResponse(status="ok", result=result)


@router.post("/v1/engine/controls/emergency-state", response_model=EmergencyStateResponse)
async def set_emergency_state(payload: EmergencyStateUpsertRequest, request: Request) -> EmergencyStateResponse:
    try:
        result = get_control_service(request.app).set_emergency_state(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return EmergencyStateResponse(status="ok", result=result)


@router.post("/v1/engine/controls/gate-patches/shadow-compare", response_model=GateShadowCompareResponse)
async def shadow_compare_gate_patch(payload: GateShadowCompareRequest, request: Request) -> GateShadowCompareResponse:
    result = get_control_service(request.app).shadow_compare(
        strategy_code=payload.strategy_code,
        baseline=payload.baseline,
        candidate=payload.candidate,
    )
    return GateShadowCompareResponse(status="ok", result=result)


@router.post("/v1/engine/controls/gate-patches/auto-promotion/evaluate", response_model=GateAutoPromotionResponse)
async def evaluate_gate_auto_promotion(payload: GateAutoPromotionRequest, request: Request) -> GateAutoPromotionResponse:
    try:
        result = get_control_service(request.app).evaluate_auto_promotion(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GateAutoPromotionResponse(status="ok", result=result)


__all__ = ["router"]
