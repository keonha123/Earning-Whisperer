"""Regression comparison and report artifact generation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

try:
    from models.storage_models import RegressionCompareRequest
    from repositories.event_store_repository import EventStoreRepository
except ImportError:  # pragma: no cover
    from ..models.storage_models import RegressionCompareRequest
    from ..repositories.event_store_repository import EventStoreRepository


@dataclass(slots=True)
class RegressionService:
    repository: EventStoreRepository

    @staticmethod
    def _score_metrics(*, hit_rate_delta: float, avg_return_delta_bps: float, drawdown_delta_bps: float, false_positive_delta: float) -> float:
        return (
            avg_return_delta_bps * 0.35
            + hit_rate_delta * 100.0 * 0.25
            + (-drawdown_delta_bps) * 0.25
            + (-false_positive_delta) * 100.0 * 0.15
        )

    @classmethod
    def compare_metrics(cls, *, strategy_code: str, suite_name: str, baseline: Any, candidate: Any, closed_replay_sample: int | None = None) -> dict[str, Any]:
        hit_rate_delta = float(candidate.hit_rate) - float(baseline.hit_rate)
        avg_return_delta_bps = float(candidate.avg_return_bps) - float(baseline.avg_return_bps)
        drawdown_delta_bps = float(candidate.max_drawdown_bps) - float(baseline.max_drawdown_bps)
        false_positive_delta = float(candidate.false_positive_rate) - float(baseline.false_positive_rate)
        sample_ratio = float(candidate.sample_size) / float(baseline.sample_size) if float(baseline.sample_size) > 0 else 1.0
        closed_replay_sample = int(closed_replay_sample if closed_replay_sample is not None else candidate.sample_size)
        score = cls._score_metrics(
            hit_rate_delta=hit_rate_delta,
            avg_return_delta_bps=avg_return_delta_bps,
            drawdown_delta_bps=drawdown_delta_bps,
            false_positive_delta=false_positive_delta,
        )
        passed = closed_replay_sample >= 20 and score > 0 and avg_return_delta_bps > 0 and false_positive_delta <= 0
        verdict = "pass" if passed else "fail"
        recommendation = "promote_candidate" if passed else "hold_candidate"
        overall = {
            "strategy_code": strategy_code,
            "suite_name": suite_name,
            "score": round(score, 4),
            "closed_replay_sample": closed_replay_sample,
            "comparison": {
                "hit_rate_delta": round(hit_rate_delta, 6),
                "avg_return_delta_bps": round(avg_return_delta_bps, 4),
                "drawdown_delta_bps": round(drawdown_delta_bps, 4),
                "false_positive_delta": round(false_positive_delta, 6),
                "sample_ratio": round(sample_ratio, 4),
            },
            "verdict": verdict,
            "promotion_recommendation": recommendation,
        }
        markdown = "\n".join(
            [
                f"# Regression Report: {strategy_code} / {suite_name}",
                "",
                f"- Verdict: `{verdict}`",
                f"- Promotion recommendation: `{recommendation}`",
                f"- Closed replay sample: `{closed_replay_sample}`",
                f"- Score: `{overall['score']}`",
                f"- Avg return delta (bps): `{overall['comparison']['avg_return_delta_bps']}`",
                f"- Hit-rate delta: `{overall['comparison']['hit_rate_delta']}`",
                f"- Drawdown delta (bps): `{overall['comparison']['drawdown_delta_bps']}`",
                f"- False-positive delta: `{overall['comparison']['false_positive_delta']}`",
            ]
        )
        return {
            "overall": overall,
            "markdown_text": markdown,
            "verdict": verdict,
            "promotion_recommendation": recommendation,
            "closed_replay_sample": closed_replay_sample,
        }

    def compare(self, payload: RegressionCompareRequest) -> dict[str, Any]:
        base = self.compare_metrics(
            strategy_code=payload.strategy_code,
            suite_name=payload.suite_name,
            baseline=payload.baseline,
            candidate=payload.candidate,
        )
        identity = f"{payload.strategy_code}:{payload.suite_name}:{payload.candidate_patch_id}:{payload.baseline_patch_id}:{base['overall']['score']}"
        report_id = f"report_{sha1(identity.encode('utf-8')).hexdigest()[:16]}"
        report_payload = {
            "report_id": report_id,
            "suite_name": payload.suite_name,
            "strategy_code": payload.strategy_code,
            "baseline_patch_id": payload.baseline_patch_id,
            "candidate_patch_id": payload.candidate_patch_id,
            "overall": base["overall"],
            "strategy_delta": payload.strategy_deltas,
            "regime_delta": payload.regime_deltas,
            "sector_delta": payload.sector_deltas,
            "market_cap_delta": payload.market_cap_deltas,
            "markdown_text": base["markdown_text"],
            "verdict": base["verdict"],
            "promotion_recommendation": base["promotion_recommendation"],
            "closed_replay_sample": base["closed_replay_sample"],
            "created_by": payload.actor,
        }
        saved = self.repository.save_regression_report(report_payload)
        return saved

    def list_reports(self, *, strategy_code: str | None = None, suite_name: str | None = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return self.repository.list_regression_reports(strategy_code=strategy_code, suite_name=suite_name, limit=limit, offset=offset)

    def get_report(self, report_id: str) -> dict[str, Any]:
        report = self.repository.get_regression_report(report_id)
        if report is None:
            raise ValueError("report_id not found")
        return report


__all__ = ["RegressionService"]
