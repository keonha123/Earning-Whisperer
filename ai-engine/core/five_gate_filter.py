from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    composite_score: float
    failed_gates: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class FiveGateFilter:
    """Small compatibility implementation for legacy integrations.

    The main strategy engine already applies richer routing and strategy gates.
    This class preserves import compatibility and provides a simple composite pass/fail gate.
    """

    def __init__(
        self,
        *,
        composite_threshold: float = 0.45,
        confidence_threshold: float = 0.70,
        raw_score_threshold: float = 0.35,
    ) -> None:
        self.composite_threshold = composite_threshold
        self.confidence_threshold = confidence_threshold
        self.raw_score_threshold = raw_score_threshold

    def evaluate(self, *, composite_score: float, confidence: float, raw_score: float) -> GateDecision:
        failed: list[str] = []
        if composite_score < self.composite_threshold:
            failed.append('composite')
        if confidence < self.confidence_threshold:
            failed.append('confidence')
        if raw_score < self.raw_score_threshold:
            failed.append('raw_score')
        return GateDecision(
            passed=not failed,
            composite_score=float(composite_score),
            failed_gates=tuple(failed),
            metadata={
                'thresholds': {
                    'composite': self.composite_threshold,
                    'confidence': self.confidence_threshold,
                    'raw_score': self.raw_score_threshold,
                }
            },
        )
