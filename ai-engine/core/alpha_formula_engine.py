from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlphaFormula:
    """Lightweight normalized factor-weight container used by profile overlays."""

    w_sentiment: float = 0.35
    w_sue: float = 0.30
    w_momentum: float = 0.20
    w_volume: float = 0.15

    def normalized(self) -> "AlphaFormula":
        total = self.w_sentiment + self.w_sue + self.w_momentum + self.w_volume
        if total <= 0:
            return AlphaFormula()
        return AlphaFormula(
            w_sentiment=self.w_sentiment / total,
            w_sue=self.w_sue / total,
            w_momentum=self.w_momentum / total,
            w_volume=self.w_volume / total,
        )
