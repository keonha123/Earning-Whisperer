from __future__ import annotations

from dataclasses import dataclass
import re

try:
    from models.request_models import MarketData, SectionType, SourceType
except ImportError:  # pragma: no cover
    from ..models.request_models import MarketData, SectionType, SourceType


@dataclass(slots=True)
class Phase1ScoreResult:
    raw_score: float
    confidence: float
    label: str = "neutral"
    provider: str = "heuristic"
    rationale_hint: str = ""


_POSITIVE_PATTERNS = [
    r"\bbeat\b",
    r"\braised guidance\b",
    r"\baccelerat(?:e|ed|ing)\b",
    r"\bmargin expanded\b",
    r"\bstrong demand\b",
    r"\bbacklog\b",
]
_NEGATIVE_PATTERNS = [
    r"\bmiss\b",
    r"\bcut guidance\b",
    r"\bslow(?:ed|ing)?\b",
    r"\bsoft demand\b",
    r"\bheadwind\b",
    r"\bweaker\b",
]


def score_phase1(
    *,
    current_chunk: str,
    market_data: MarketData,
    section_type: SectionType,
    source_type: SourceType,
) -> Phase1ScoreResult:
    text = (current_chunk or "").lower()
    positive_hits = sum(1 for p in _POSITIVE_PATTERNS if re.search(p, text))
    negative_hits = sum(1 for p in _NEGATIVE_PATTERNS if re.search(p, text))
    numeric_hits = len(re.findall(r"\b\d+(?:\.\d+)?\b|\d+%|bps|basis points", text, flags=re.I))

    raw_score = 0.0
    raw_score += positive_hits * 1.2
    raw_score -= negative_hits * 1.0
    raw_score += min(1.5, numeric_hits * 0.25)
    raw_score += min(1.0, max(0.0, (market_data.volume_ratio - 1.0) * 0.3))
    raw_score += min(0.8, max(0.0, market_data.surprise_pct) * 0.04)

    if section_type == SectionType.Q_AND_A:
        raw_score *= 0.9
    if source_type == SourceType.NEWS:
        raw_score *= 1.05

    confidence = min(0.95, 0.45 + positive_hits * 0.08 + numeric_hits * 0.03 + max(0.0, market_data.volume_ratio - 1.0) * 0.04)
    if raw_score >= 2.8:
        label = "pass"
    elif raw_score >= 1.2:
        label = "review"
    else:
        label = "drop"
    rationale_hint = f"positive={positive_hits}, negative={negative_hits}, numeric={numeric_hits}"
    return Phase1ScoreResult(raw_score=round(raw_score, 4), confidence=round(confidence, 4), label=label, provider="heuristic", rationale_hint=rationale_hint)
