from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AnalysisGuard:
    sentiment_threshold: float = 0.55
    confidence_threshold: float = 0.60
    risk_threshold: float = 0.70

    def assess(self, *, sentiment_score: float, confidence: float, risk_score: float) -> dict[str, float | bool]:
        directional_conviction = abs(sentiment_score)
        needs_review = (
            directional_conviction >= self.sentiment_threshold
            and (confidence < self.confidence_threshold or risk_score >= self.risk_threshold)
        )
        return {
            "needs_review": needs_review,
            "directional_conviction": directional_conviction,
            "confidence": confidence,
            "risk_score": risk_score,
        }
