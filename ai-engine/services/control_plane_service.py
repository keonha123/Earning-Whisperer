"""Product-grade control, rollout, and runtime decision orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

try:
    from models.request_models import AnalyzeRequest
    from models.storage_models import (
        EmergencyStateUpsertRequest,
        GateAutoPromotionRequest,
        GatePatchDecisionRequest,
        GateRolloutActionRequest,
        GateRolloutCreateRequest,
        RegressionCompareRequest,
    )
    from repositories.event_store_repository import EventStoreRepository
    from services.regression_service import RegressionService
except ImportError:  # pragma: no cover
    from ..models.request_models import AnalyzeRequest
    from ..models.storage_models import (
        EmergencyStateUpsertRequest,
        GateAutoPromotionRequest,
        GatePatchDecisionRequest,
        GateRolloutActionRequest,
        GateRolloutCreateRequest,
        RegressionCompareRequest,
    )
    from ..repositories.event_store_repository import EventStoreRepository
    from .regression_service import RegressionService


@dataclass(slots=True)
class ControlPlaneService:
    repository: EventStoreRepository

    _ROLLOUT_SEQUENCE = (10, 25, 50, 100)
    _ROLLOUT_RULES = {
        25: {"closed_replay_sample": 20, "min_score": 3.0, "require_positive_return": True, "max_false_positive_delta": 0.0},
        50: {"closed_replay_sample": 40, "min_score": 3.0, "require_positive_return": True, "max_false_positive_delta": 0.0},
        100: {"closed_replay_sample": 80, "min_score": 3.0, "require_positive_return": True, "max_false_positive_delta": 0.0},
    }

    @staticmethod
    def deterministic_rollout_bucket(*, event_id: str, strategy_code: str) -> int:
        raw = f"{event_id}:{strategy_code}".encode("utf-8")
        return int(sha1(raw).hexdigest()[:8], 16) % 100

    def shadow_compare(self, *, strategy_code: str, baseline: Any, candidate: Any) -> dict[str, Any]:
        compared = RegressionService.compare_metrics(
            strategy_code=strategy_code,
            suite_name="shadow_compare",
            baseline=baseline,
            candidate=candidate,
        )
        overall = compared["overall"]
        score = overall["score"]
        comparison = overall["comparison"]
        if candidate.sample_size < 30 or comparison["sample_ratio"] < 0.5:
            decision = "review"
            reason_ko = "후보 설정의 표본 수가 충분하지 않아 즉시 승격보다 추가 검증이 필요합니다."
        elif score >= 3.0 and comparison["avg_return_delta_bps"] > 0 and comparison["false_positive_delta"] <= 0:
            decision = "promote"
            reason_ko = "후보 설정이 평균 수익률과 품질 지표에서 우위라 승격 후보로 적절합니다."
        elif score <= -3.0:
            decision = "reject"
            reason_ko = "후보 설정의 성과 열위가 명확해 적용을 보류하는 편이 적절합니다."
        else:
            decision = "review"
            reason_ko = "개선 폭이 제한적이어서 shadow 기간 추가 검증이 필요합니다."
        return {
            "strategy_code": strategy_code,
            "decision": decision,
            "reason_ko": reason_ko,
            "score": score,
            "comparison": comparison,
        }

    def evaluate_auto_promotion(self, payload: GateAutoPromotionRequest) -> dict[str, Any]:
        report = None
        if payload.report_id:
            report = self.repository.get_regression_report(payload.report_id)
            if report is None:
                raise ValueError("report_id not found")
        else:
            report = RegressionService(self.repository).compare_from_auto_promotion(payload)  # type: ignore[attr-defined]
        overall = report["overall"]
        policy = payload.policy
        comparison = overall["comparison"]
        reasons: list[str] = []
        passed = True
        if overall["score"] < policy.min_score:
            passed = False
            reasons.append("점수가 자동 승격 기준에 미달합니다.")
        if overall["closed_replay_sample"] < policy.min_sample_size:
            passed = False
            reasons.append("표본 수가 자동 승격 기준보다 부족합니다.")
        if policy.require_positive_avg_return_delta and comparison["avg_return_delta_bps"] <= 0:
            passed = False
            reasons.append("평균 수익률 개선이 확인되지 않았습니다.")
        if comparison["false_positive_delta"] > policy.max_false_positive_delta:
            passed = False
            reasons.append("거짓 양성 증가 폭이 허용 기준을 초과했습니다.")
        decision = "promote_candidate" if passed else "holdout"
        action = "none"
        rollout_plan = {"mode": "semi-auto", "stages": [10, 25, 50, 100]}
        patch = self.repository.get_gate_patch(payload.target_patch_id) if payload.target_patch_id is not None else None
        patch_preapproved = bool(patch and str(patch.get("approval_state")) == "approved")
        approval_required = not (payload.approved_for_prod or payload.strict_prod_policy_passed or patch_preapproved)
        if passed and payload.target_patch_id is not None:
            if patch is None:
                raise ValueError("target_patch_id not found")
            self.repository.save_patch_audit_log(
                patch_id=payload.target_patch_id,
                event_type="auto_promotion_evaluated",
                status_from=patch.get("status"),
                status_to=patch.get("status"),
                approval_state_from=patch.get("approval_state"),
                approval_state_to=patch.get("approval_state"),
                payload={
                    "report_id": report["report_id"],
                    "decision": decision,
                    "reasons": reasons,
                },
                actor=payload.actor,
            )
            if passed and policy.auto_apply and not approval_required:
                apply_result = self.repository.apply_gate_patch(payload.target_patch_id, actor=payload.actor)
                action = "auto_applied"
            else:
                apply_result = None
        else:
            apply_result = None
        return {
            "strategy_code": payload.strategy_code,
            "target_patch_id": payload.target_patch_id,
            "decision": decision,
            "action": action,
            "score": overall["score"],
            "reason_ko": " ".join(reasons) if reasons else "자동 승격 정책 기준을 충족했습니다.",
            "comparison": comparison,
            "apply_result": apply_result,
            "report_id": report["report_id"],
            "rollout_plan": rollout_plan,
            "approval_required": approval_required,
        }

    def approve_patch(self, patch_id: int, payload: GatePatchDecisionRequest) -> dict[str, Any]:
        return self.repository.approve_gate_patch(
            patch_id,
            actor=payload.actor,
            note=payload.note,
            approved_for_prod=payload.approved_for_prod,
            strict_prod_policy_passed=payload.strict_prod_policy_passed,
        )

    def reject_patch(self, patch_id: int, payload: GatePatchDecisionRequest) -> dict[str, Any]:
        return self.repository.reject_gate_patch(
            patch_id,
            actor=payload.actor,
            note=payload.note,
        )

    def get_patch_audit(self, patch_id: int) -> dict[str, Any]:
        patch = self.repository.get_gate_patch(patch_id)
        if patch is None:
            raise ValueError("patch_id not found")
        return self.repository.get_gate_patch_audit(patch_id)

    def start_rollout(self, patch_id: int, payload: GateRolloutCreateRequest) -> dict[str, Any]:
        return self.repository.create_rollout(
            patch_id=patch_id,
            actor=payload.actor,
            note=payload.note,
            report_id=payload.report_id,
            initial_stage_pct=payload.initial_stage_pct,
            mode=payload.mode,
        )

    def list_rollouts(self, *, strategy_code: str | None = None, status: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return self.repository.list_rollouts(strategy_code=strategy_code, status=status, limit=limit, offset=offset)

    def get_rollout(self, rollout_id: int) -> dict[str, Any]:
        rollout = self.repository.get_rollout(rollout_id)
        if rollout is None:
            raise ValueError("rollout_id not found")
        return rollout

    def _validate_rollout_stage(self, *, report: dict[str, Any], next_stage_pct: int, approved_for_prod: bool, strict_prod_policy_passed: bool) -> tuple[bool, list[str]]:
        requirements = self._ROLLOUT_RULES[next_stage_pct]
        overall = report["overall"]
        comparison = overall["comparison"]
        reasons: list[str] = []
        if overall["closed_replay_sample"] < requirements["closed_replay_sample"]:
            reasons.append("closed replay sample 부족")
        if overall["score"] < requirements["min_score"]:
            reasons.append("score 기준 미달")
        if requirements["require_positive_return"] and comparison["avg_return_delta_bps"] <= 0:
            reasons.append("avg_return_delta 양수 미충족")
        if comparison["false_positive_delta"] > requirements["max_false_positive_delta"]:
            reasons.append("false_positive_delta 기준 초과")
        if next_stage_pct == 100 and not (approved_for_prod or strict_prod_policy_passed):
            reasons.append("100% 승격은 approve 또는 stricter prod policy 통과가 필요")
        return (not reasons, reasons)

    def advance_rollout(self, rollout_id: int, payload: GateRolloutActionRequest) -> dict[str, Any]:
        rollout = self.get_rollout(rollout_id)
        if rollout["status"] in {"aborted", "prod_active", "rolled_back"}:
            raise ValueError("rollout is not advanceable")
        report_id = payload.report_id or rollout.get("report_id")
        if not report_id:
            raise ValueError("report_id is required to advance rollout")
        report = self.repository.get_regression_report(report_id)
        if report is None:
            raise ValueError("report_id not found")
        current_stage = int(rollout.get("current_stage_pct") or 10)
        try:
            next_stage = self._ROLLOUT_SEQUENCE[self._ROLLOUT_SEQUENCE.index(current_stage) + 1]
        except (ValueError, IndexError) as exc:
            raise ValueError("rollout is already at final stage") from exc
        passed, reasons = self._validate_rollout_stage(
            report=report,
            next_stage_pct=next_stage,
            approved_for_prod=payload.approved_for_prod or bool(rollout.get("approved_for_prod")),
            strict_prod_policy_passed=payload.strict_prod_policy_passed or bool(rollout.get("strict_prod_policy_passed")),
        )
        if not passed:
            self.repository.save_rollout_stage_event(
                rollout_id=rollout_id,
                from_stage_pct=current_stage,
                to_stage_pct=next_stage,
                event_type="advance_blocked",
                verdict="blocked",
                payload={"reasons": reasons, "report_id": report_id},
                actor=payload.actor,
            )
            raise ValueError("; ".join(reasons))
        updated = self.repository.advance_rollout(
            rollout_id=rollout_id,
            to_stage_pct=next_stage,
            actor=payload.actor,
            note=payload.note,
            report_id=report_id,
            approved_for_prod=payload.approved_for_prod,
            strict_prod_policy_passed=payload.strict_prod_policy_passed,
        )
        if next_stage == 100:
            self.repository.apply_gate_patch(int(rollout["patch_id"]), actor=payload.actor)
        return updated

    def abort_rollout(self, rollout_id: int, payload: GateRolloutActionRequest) -> dict[str, Any]:
        return self.repository.abort_rollout(rollout_id=rollout_id, actor=payload.actor, note=payload.note)

    def get_emergency_state(self, *, control_type: str | None = None, scope_type: str | None = None, scope_key: str | None = None) -> dict[str, Any]:
        return self.repository.list_control_states(control_type=control_type, scope_type=scope_type, scope_key=scope_key)

    def set_emergency_state(self, payload: EmergencyStateUpsertRequest) -> dict[str, Any]:
        result = self.repository.set_control_state(
            control_type=payload.control_type,
            enabled=payload.enabled,
            scope_type=payload.scope_type,
            scope_key=payload.scope_key,
            note=payload.note,
            actor=payload.actor,
        )
        if payload.control_type == "global_kill_switch" and payload.enabled:
            active_rollouts = self.repository.list_rollouts(status="active", limit=500, offset=0).get("items", [])
            aborted_rollouts = []
            for rollout in active_rollouts:
                aborted_rollouts.append(self.repository.abort_rollout(int(rollout["rollout_id"]), actor=payload.actor, note="global_kill_switch"))
            result["aborted_rollouts"] = aborted_rollouts
            active_configs = self.repository.list_active_gate_configs(limit=500, offset=0).get("items", [])
            reverted = []
            for config in active_configs:
                baseline_patch = self.repository.find_latest_patch(
                    strategy_code=str(config["strategy_code"]),
                    status="prod_active",
                    scope_type="strategy_global",
                    exclude_patch_id=config.get("active_patch_id"),
                )
                if baseline_patch:
                    reverted.append(
                        self.repository.rollback_active_gate_config(
                            str(config["strategy_code"]),
                            target_patch_id=int(baseline_patch["patch_id"]),
                            actor=payload.actor,
                        )
                    )
            result["baseline_reverts"] = reverted
        return result

    def apply_runtime_controls(self, *, payload: AnalyzeRequest, analysis: dict[str, Any], event_id: str | None = None) -> dict[str, Any]:
        strategy_code = str(analysis.get("strategy") or analysis.get("metadata", {}).get("strategy_code") or "SENTIMENT_ONLY")
        event_id = event_id or f"evt_{payload.ticker.lower()}_{payload.chunk_sequence:03d}"
        market_data = payload.market_data
        regime = "high_vol" if float(market_data.vix or 0.0) >= 25.0 else "normal"
        ticker = payload.ticker.upper()
        sector_code = market_data.sector_code or None
        market_cap_bucket = market_data.market_cap_bucket or self.repository.normalize_market_cap_bucket(market_data.market_cap)
        active_patch = self.repository.resolve_active_patch(
            strategy_code=strategy_code,
            ticker=ticker,
            sector_code=sector_code,
            market_cap_bucket=market_cap_bucket,
            regime=regime,
            universe_profile=payload.universe_profile,
        )
        rollout_bucket = self.deterministic_rollout_bucket(event_id=event_id, strategy_code=strategy_code)
        control_states = self.repository.get_effective_control_states(
            strategy_code=strategy_code,
            universe_profile=payload.universe_profile,
        )
        control_blocks: list[dict[str, str]] = []
        execution_allowed = True
        decision_state = "tradable"
        blocked_reason_ko = None

        if any(state.get("control_type") == "global_kill_switch" and state.get("enabled") for state in control_states):
            execution_allowed = False
            decision_state = "blocked"
            blocked_reason_ko = "글로벌 킬 스위치가 활성화되어 신규 시그널 실행이 차단되었습니다."
            control_blocks.append({"type": "control_blocks", "reason_ko": blocked_reason_ko})
        elif any(state.get("control_type") == "signal_suppress" and state.get("enabled") for state in control_states):
            execution_allowed = False
            decision_state = "suppressed"
            blocked_reason_ko = "신호 억제 상태로 인해 분석은 수행되지만 실행/발행 경로는 차단됩니다."
            control_blocks.append({"type": "control_blocks", "reason_ko": blocked_reason_ko})

        gate_failures: list[dict[str, Any]] = []
        if active_patch:
            thresholds = self.repository.materialize_thresholds(
                strategy_code=strategy_code,
                patch_json=active_patch.get("patch_json") or {},
            )
            score = float((analysis.get("metadata") or {}).get("strategy_score") or 0.0)
            magnitude = float(analysis.get("magnitude") or 0.0)
            confidence = float(analysis.get("confidence") or 0.0)
            volume_ratio = float(market_data.volume_ratio or 0.0)
            event_quality = self.repository.extract_event_quality(analysis)
            gap_overshoot = self.repository.compute_gap_overshoot(market_data)
            if confidence < thresholds["min_confidence"]:
                gate_failures.append({"feature": "confidence", "reason_ko": "최소 confidence 기준 미달", "threshold": thresholds["min_confidence"], "value": confidence})
            if score < thresholds["min_composite"]:
                gate_failures.append({"feature": "strategy_score", "reason_ko": "최소 composite 기준 미달", "threshold": thresholds["min_composite"], "value": score})
            if magnitude < thresholds["min_raw_score"]:
                gate_failures.append({"feature": "raw_score", "reason_ko": "최소 raw score 기준 미달", "threshold": thresholds["min_raw_score"], "value": magnitude})
            if volume_ratio < thresholds["min_volume_ratio"]:
                gate_failures.append({"feature": "volume_ratio", "reason_ko": "최소 거래량 비율 기준 미달", "threshold": thresholds["min_volume_ratio"], "value": volume_ratio})
            if event_quality < thresholds["min_event_quality"]:
                gate_failures.append({"feature": "event_quality", "reason_ko": "최소 event quality 기준 미달", "threshold": thresholds["min_event_quality"], "value": event_quality})
            if gap_overshoot > thresholds["max_gap_overshoot"]:
                gate_failures.append({"feature": "gap_overshoot", "reason_ko": "과도한 갭 과열로 차단", "threshold": thresholds["max_gap_overshoot"], "value": gap_overshoot})
            analysis["hold_days"] = max(1, int(analysis.get("hold_days") or 1) + int(thresholds["max_hold_days_delta"]))
            analysis.setdefault("metadata", {})
            analysis["metadata"]["position_scale_delta"] = thresholds["position_scale_delta"]

        if gate_failures and execution_allowed:
            execution_allowed = False
            decision_state = "blocked"
            blocked_reason_ko = gate_failures[0]["reason_ko"]

        return {
            "execution_allowed": execution_allowed,
            "blocked_reason_ko": blocked_reason_ko,
            "gate_failures": gate_failures,
            "control_overrides": control_states,
            "blocked_reasons": {
                "gate_rejections": gate_failures,
                "control_blocks": control_blocks,
                "risk_overrides": [],
            },
            "decision_state": decision_state,
            "active_patch_id": active_patch.get("patch_id") if active_patch else None,
            "calibration_segment": active_patch.get("scope_type") if active_patch else None,
            "rollout_bucket": rollout_bucket,
        }


def _compare_from_auto_promotion(self, payload: GateAutoPromotionRequest) -> dict[str, Any]:
    return self.compare(
        RegressionCompareRequest(
            strategy_code=payload.strategy_code,
            suite_name=payload.suite_name or "prod_guardrail_core",
            candidate_patch_id=payload.target_patch_id,
            baseline_patch_id=None,
            actor=payload.actor,
            baseline=payload.baseline,
            candidate=payload.candidate,
        )
    )


RegressionService.compare_from_auto_promotion = _compare_from_auto_promotion  # type: ignore[attr-defined]


__all__ = ["ControlPlaneService"]
