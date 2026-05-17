"""Hierarchical calibration proposal generation for gate patches."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

try:
    from models.storage_models import CalibrationRunRequest
    from repositories.event_store_repository import EventStoreRepository
except ImportError:  # pragma: no cover
    from ..models.storage_models import CalibrationRunRequest
    from ..repositories.event_store_repository import EventStoreRepository


@dataclass(slots=True)
class CalibrationService:
    repository: EventStoreRepository

    _PARAM_BOUNDS = {
        "min_confidence_delta": (-0.10, 0.20, (-0.03, 0.0, 0.03, 0.05, 0.08)),
        "min_composite": (0.35, 0.85, (-0.05, 0.0, 0.05)),
        "min_raw_score": (0.20, 0.90, (-0.05, 0.0, 0.05)),
        "min_volume_ratio": (0.8, 5.0, (-0.2, 0.0, 0.2)),
        "min_event_quality": (0.0, 1.0, (-0.05, 0.0, 0.05)),
        "max_gap_overshoot": (0.0, 12.0, (-0.5, 0.0, 0.5)),
        "position_scale_delta": (-0.6, 0.3, (-0.1, 0.0, 0.1)),
        "max_hold_days_delta": (-3, 3, (-1, 0, 1)),
    }
    _SAMPLE_FLOORS = {
        "ticker": 80,
        "sector_cap": 50,
        "sector": 40,
        "regime": 30,
        "global": 25,
    }
    _SCOPE_ORDER = ("ticker", "sector_cap", "sector", "regime", "global")

    def _build_segments(self, records: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in records:
            ticker = str(row.get("ticker") or "UNKNOWN")
            sector_code = str(row.get("sector_code") or row.get("sector") or "unknown")
            cap_bucket = str(row.get("market_cap_bucket") or "unknown")
            regime = str(row.get("regime") or "normal")
            grouped[("global", "all")].append(row)
            grouped[("regime", regime)].append(row)
            grouped[("sector", sector_code)].append(row)
            grouped[("sector_cap", f"{sector_code}:{cap_bucket}")].append(row)
            grouped[("ticker", ticker)].append(row)
        return grouped

    @staticmethod
    def _split_train_holdout(records: list[dict[str, Any]], holdout_size: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ordered = sorted(records, key=lambda item: str(item.get("event_time") or item.get("created_at") or ""))
        if not ordered:
            return [], []
        holdout_size = max(1, min(len(ordered) // 3, holdout_size))
        return ordered[:-holdout_size], ordered[-holdout_size:]

    def _score_selection(self, rows: list[dict[str, Any]], thresholds: dict[str, float]) -> dict[str, float]:
        selected = []
        for row in rows:
            if float(row.get("confidence") or 0.0) < thresholds["min_confidence"]:
                continue
            if float(row.get("strategy_score") or 0.0) < thresholds["min_composite"]:
                continue
            if float(row.get("magnitude") or 0.0) < thresholds["min_raw_score"]:
                continue
            if float(row.get("volume_ratio") or 0.0) < thresholds["min_volume_ratio"]:
                continue
            if float(row.get("event_quality") or 0.0) < thresholds["min_event_quality"]:
                continue
            if float(row.get("gap_overshoot") or 0.0) > thresholds["max_gap_overshoot"]:
                continue
            selected.append(row)
        if not selected:
            return {"score": -999.0, "avg_return": 0.0, "win_rate": 0.0, "false_positive_rate": 1.0, "sample_size": 0}
        sample_size = len(selected)
        avg_return = sum(float(item.get("realized_pnl_pct") or 0.0) for item in selected) / sample_size
        wins = sum(1 for item in selected if float(item.get("realized_pnl_pct") or 0.0) > 0.0)
        false_positives = sum(1 for item in selected if float(item.get("realized_pnl_pct") or 0.0) <= 0.0)
        win_rate = wins / sample_size
        false_positive_rate = false_positives / sample_size
        avg_mae = sum(abs(float(item.get("mae_pct") or 0.0)) for item in selected) / sample_size
        score = avg_return * 100.0 * 0.35 + win_rate * 100.0 * 0.25 + (-avg_mae * 100.0) * 0.25 + (-false_positive_rate * 100.0) * 0.15
        return {
            "score": round(score, 4),
            "avg_return": round(avg_return, 6),
            "win_rate": round(win_rate, 6),
            "false_positive_rate": round(false_positive_rate, 6),
            "sample_size": sample_size,
        }

    def _candidate_thresholds(self, *, strategy_code: str, base_patch: dict[str, Any]) -> list[dict[str, Any]]:
        defaults = self.repository.materialize_thresholds(strategy_code=strategy_code, patch_json=base_patch)
        candidates: list[dict[str, Any]] = []
        for confidence_delta in self._PARAM_BOUNDS["min_confidence_delta"][2]:
            for composite_delta in self._PARAM_BOUNDS["min_composite"][2]:
                for volume_delta in self._PARAM_BOUNDS["min_volume_ratio"][2]:
                    candidate = dict(defaults)
                    candidate["min_confidence"] = max(0.0, min(1.0, defaults["min_confidence"] + float(confidence_delta)))
                    candidate["min_composite"] = max(0.0, min(1.0, defaults["min_composite"] + float(composite_delta)))
                    candidate["min_raw_score"] = max(0.0, min(1.0, defaults["min_raw_score"] + float(composite_delta)))
                    candidate["min_volume_ratio"] = max(0.5, defaults["min_volume_ratio"] + float(volume_delta))
                    candidates.append(candidate)
        return candidates[:30]

    def _proposal_patch(self, *, strategy_code: str, thresholds: dict[str, float], base: dict[str, float], segment_type: str, segment_key: str, actor: str | None) -> dict[str, Any]:
        patch = {
            "min_confidence_delta": round(thresholds["min_confidence"] - base["min_confidence"], 4),
            "min_composite": round(thresholds["min_composite"], 4),
            "min_raw_score": round(thresholds["min_raw_score"], 4),
            "min_volume_ratio": round(thresholds["min_volume_ratio"], 4),
            "min_event_quality": round(thresholds["min_event_quality"], 4),
            "max_gap_overshoot": round(thresholds["max_gap_overshoot"], 4),
            "position_scale_delta": round(thresholds["position_scale_delta"], 4),
            "max_hold_days_delta": int(round(thresholds["max_hold_days_delta"])),
        }
        scope_type = {
            "global": "strategy_global",
            "regime": "strategy_regime",
            "sector": "strategy_sector",
            "sector_cap": "strategy_sector_cap",
            "ticker": "strategy_ticker",
        }[segment_type]
        return self.repository.save_gate_patch(
            {
                "strategy_code": strategy_code,
                "patch": patch,
                "rationale_ko": f"{segment_type} 세그먼트({segment_key}) 기준 calibration proposal",
                "source": "auto_calibration",
                "applied": False,
                "created_by": actor,
                "patch_type": "calibration",
                "scope_type": scope_type,
                "scope_key": segment_key,
                "regime": segment_key if segment_type == "regime" else None,
                "sector_code": segment_key.split(":")[0] if segment_type in {"sector", "sector_cap"} else None,
                "market_cap_bucket": segment_key.split(":")[1] if segment_type == "sector_cap" and ":" in segment_key else None,
                "ticker": segment_key if segment_type == "ticker" else None,
                "status": "draft",
                "approval_state": "proposal",
            }
        )

    def run(self, payload: CalibrationRunRequest) -> dict[str, Any]:
        rows = self.repository.get_closed_replay_samples(strategy_code=payload.strategy_code, lookback_days=payload.lookback_days)
        if not rows:
            return {"strategy_code": payload.strategy_code, "proposal_count": 0, "items": [], "reason_ko": "closed replay 샘플이 없어 calibration proposal을 생성하지 않았습니다."}
        base_patch = self.repository.resolve_active_patch(strategy_code=payload.strategy_code) or {"patch_json": {}}
        base_thresholds = self.repository.materialize_thresholds(strategy_code=payload.strategy_code, patch_json=base_patch.get("patch_json") or {})
        proposals: list[dict[str, Any]] = []
        for (segment_type, segment_key), segment_rows in self._build_segments(rows).items():
            floor = self._SAMPLE_FLOORS[segment_type]
            if len(segment_rows) < floor:
                continue
            train, holdout = self._split_train_holdout(segment_rows, payload.holdout_days)
            if len(train) < max(10, floor // 2) or len(holdout) < 5:
                continue
            best_thresholds = None
            best_train_score = -999.0
            best_holdout = {"score": -999.0}
            for candidate in self._candidate_thresholds(strategy_code=payload.strategy_code, base_patch=base_patch.get("patch_json") or {}):
                train_score = self._score_selection(train, candidate)
                if train_score["score"] <= best_train_score:
                    continue
                holdout_score = self._score_selection(holdout, candidate)
                if holdout_score["score"] <= 0:
                    continue
                best_thresholds = candidate
                best_train_score = train_score["score"]
                best_holdout = holdout_score
            if not best_thresholds:
                continue
            patch_result = self._proposal_patch(
                strategy_code=payload.strategy_code,
                thresholds=best_thresholds,
                base=base_thresholds,
                segment_type=segment_type,
                segment_key=segment_key,
                actor=payload.actor,
            )
            hold_stats = self.repository.compute_hold_tuning_snapshot(segment_rows)
            self.repository.save_hold_tuning_snapshot(
                strategy_code=payload.strategy_code,
                segment_type=segment_type,
                segment_key=segment_key,
                snapshot=hold_stats,
            )
            proposal_result = self.repository.save_calibration_proposal(
                {
                    "patch_id": patch_result["patch_id"],
                    "strategy_code": payload.strategy_code,
                    "segment_type": segment_type,
                    "segment_key": segment_key,
                    "proposal_json": patch_result.get("patch_json") or {},
                    "summary_json": {
                        "sample_size": len(segment_rows),
                        "train_score": best_train_score,
                        "holdout_score": best_holdout["score"],
                        "hold_stats": hold_stats,
                    },
                    "created_by": payload.actor,
                }
            )
            proposals.append(proposal_result)
            if len(proposals) >= payload.max_candidates:
                break
        return {
            "strategy_code": payload.strategy_code,
            "proposal_count": len(proposals),
            "items": proposals,
            "learning_mode": "patch proposal",
        }

    def list_proposals(self, *, strategy_code: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return self.repository.list_calibration_proposals(strategy_code=strategy_code, limit=limit, offset=offset)

    def get_proposal(self, proposal_id: int) -> dict[str, Any]:
        proposal = self.repository.get_calibration_proposal(proposal_id)
        if proposal is None:
            raise ValueError("proposal_id not found")
        return proposal

    def promote(self, proposal_id: int, *, actor: str | None = None, note: str | None = None) -> dict[str, Any]:
        proposal = self.get_proposal(proposal_id)
        self.repository.mark_calibration_proposal_promoted(proposal_id, actor=actor)
        return {
            "proposal_id": proposal_id,
            "patch_id": proposal.get("patch_id"),
            "strategy_code": proposal.get("strategy_code"),
            "status": "promotion_ready",
            "note": note,
            "requires_rollout": True,
        }


__all__ = ["CalibrationService"]
