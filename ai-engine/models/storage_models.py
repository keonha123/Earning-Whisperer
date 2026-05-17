from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersistEnvelopeResponse(BaseModel):
    status: str = "ok"
    persisted: bool = True
    event_id: str
    run_id: str
    row_counts: dict[str, int] = Field(default_factory=dict)


class AnalyzeAndPersistResponse(BaseModel):
    status: str = "ok"
    persisted: bool = True
    event_id: str
    run_id: str
    row_counts: dict[str, int] = Field(default_factory=dict)
    envelope: dict[str, Any]


class BootstrapSchemaResponse(BaseModel):
    status: str = "ok"
    applied: bool = True
    schema_path: str


class RunBundleResponse(BaseModel):
    status: str = "ok"
    run_id: str
    bundle: dict[str, Any]


class EventBundleResponse(BaseModel):
    status: str = "ok"
    event_id: str
    bundle: dict[str, Any]


class ReplayPatchRequest(BaseModel):
    status: str | None = None
    original_signal: dict[str, Any] | None = None
    milestones: list[dict[str, Any]] | None = None
    expected_path: str | None = None
    exit_watch: str | None = None
    realized_pnl_pct: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    close_reason: str | None = None


class ReplayPatchResponse(BaseModel):
    status: str = "ok"
    updated: bool
    run_id: str
    fields_updated: list[str] = Field(default_factory=list)


class RunListResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class MetricsOverviewResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class QualityScorecardResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class StrategyDriftResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class StrategyLeaderboardResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class ControlRecommendationsResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GateTuningResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class AlertEvaluationResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class ShadowScenarioMetrics(BaseModel):
    hit_rate: float
    avg_return_bps: float
    max_drawdown_bps: float
    false_positive_rate: float
    sample_size: int


class GateShadowCompareRequest(BaseModel):
    strategy_code: str
    baseline: ShadowScenarioMetrics
    candidate: ShadowScenarioMetrics


class GateShadowCompareResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GatePatchUpsertRequest(BaseModel):
    strategy_code: str
    patch: dict[str, Any]
    rationale_ko: str | None = None
    source: str | None = None
    applied: bool = False
    created_by: str | None = None
    patch_type: str = "manual"
    scope_type: str = "strategy_global"
    scope_key: str | None = None
    regime: str | None = None
    sector_code: str | None = None
    market_cap_bucket: str | None = None
    ticker: str | None = None
    universe_profile: str | None = None
    parent_patch_id: int | None = None
    report_id: str | None = None
    status: str | None = None
    approval_state: str | None = None


class GatePatchUpsertResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GatePatchListResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GatePatchApplyRequest(BaseModel):
    actor: str | None = None


class GatePatchApplyResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class ActiveGateConfigListResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GateConfigRollbackRequest(BaseModel):
    target_patch_id: int
    actor: str | None = None


class GateConfigRollbackResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class AlertStateUpsertRequest(BaseModel):
    code: str
    scope: str = "global"
    status: str
    note: str | None = None
    muted_until: datetime | None = None
    actor: str | None = None


class AlertStateUpsertResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class AlertStateListResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class AutoPromotionPolicy(BaseModel):
    min_score: float = 3.0
    min_sample_size: int = 30
    require_positive_avg_return_delta: bool = True
    max_false_positive_delta: float = 0.0
    auto_apply: bool = False


class GateAutoPromotionRequest(BaseModel):
    strategy_code: str
    target_patch_id: int | None = None
    baseline: ShadowScenarioMetrics
    candidate: ShadowScenarioMetrics
    policy: AutoPromotionPolicy = Field(default_factory=AutoPromotionPolicy)
    actor: str | None = None
    report_id: str | None = None
    suite_name: str | None = None
    approved_for_prod: bool = False
    strict_prod_policy_passed: bool = False


class GateAutoPromotionResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GatePatchDecisionRequest(BaseModel):
    actor: str | None = None
    note: str | None = None
    approved_for_prod: bool = False
    strict_prod_policy_passed: bool = False


class GatePatchDecisionResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GatePatchAuditResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GateRolloutCreateRequest(BaseModel):
    actor: str | None = None
    note: str | None = None
    report_id: str | None = None
    initial_stage_pct: int = 10
    mode: str = "semi-auto"


class GateRolloutActionRequest(BaseModel):
    actor: str | None = None
    note: str | None = None
    report_id: str | None = None
    approved_for_prod: bool = False
    strict_prod_policy_passed: bool = False


class GateRolloutResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class GateRolloutListResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class EmergencyStateUpsertRequest(BaseModel):
    control_type: str
    enabled: bool = True
    scope_type: str = "global"
    scope_key: str | None = None
    note: str | None = None
    actor: str | None = None


class EmergencyStateResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class CalibrationRunRequest(BaseModel):
    strategy_code: str
    lookback_days: int = 180
    holdout_days: int = 30
    actor: str | None = None
    universe_profile: str | None = None
    max_candidates: int = 10


class CalibrationPromoteRequest(BaseModel):
    actor: str | None = None
    note: str | None = None
    report_id: str | None = None


class CalibrationResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class RegressionCompareRequest(BaseModel):
    strategy_code: str
    suite_name: str
    candidate_patch_id: int | None = None
    baseline_patch_id: int | None = None
    actor: str | None = None
    baseline: ShadowScenarioMetrics
    candidate: ShadowScenarioMetrics
    regime_deltas: dict[str, dict[str, float]] = Field(default_factory=dict)
    sector_deltas: dict[str, dict[str, float]] = Field(default_factory=dict)
    market_cap_deltas: dict[str, dict[str, float]] = Field(default_factory=dict)
    strategy_deltas: dict[str, dict[str, float]] = Field(default_factory=dict)
    false_positive_delta: float | None = None


class RegressionReportResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


class RegressionReportListResponse(BaseModel):
    status: str = "ok"
    result: dict[str, Any]


__all__ = [
    "PersistEnvelopeResponse",
    "AnalyzeAndPersistResponse",
    "BootstrapSchemaResponse",
    "RunBundleResponse",
    "EventBundleResponse",
    "ReplayPatchRequest",
    "ReplayPatchResponse",
    "RunListResponse",
    "MetricsOverviewResponse",
    "QualityScorecardResponse",
    "StrategyDriftResponse",
    "StrategyLeaderboardResponse",
    "ControlRecommendationsResponse",
    "GateTuningResponse",
    "AlertEvaluationResponse",
    "ShadowScenarioMetrics",
    "GateShadowCompareRequest",
    "GateShadowCompareResponse",
    "GatePatchUpsertRequest",
    "GatePatchUpsertResponse",
    "GatePatchListResponse",
    "GatePatchApplyRequest",
    "GatePatchApplyResponse",
    "ActiveGateConfigListResponse",
    "GateConfigRollbackRequest",
    "GateConfigRollbackResponse",
    "AlertStateUpsertRequest",
    "AlertStateUpsertResponse",
    "AlertStateListResponse",
    "AutoPromotionPolicy",
    "GateAutoPromotionRequest",
    "GateAutoPromotionResponse",
    "GatePatchDecisionRequest",
    "GatePatchDecisionResponse",
    "GatePatchAuditResponse",
    "GateRolloutCreateRequest",
    "GateRolloutActionRequest",
    "GateRolloutResponse",
    "GateRolloutListResponse",
    "EmergencyStateUpsertRequest",
    "EmergencyStateResponse",
    "CalibrationRunRequest",
    "CalibrationPromoteRequest",
    "CalibrationResponse",
    "RegressionCompareRequest",
    "RegressionReportResponse",
    "RegressionReportListResponse",
]
