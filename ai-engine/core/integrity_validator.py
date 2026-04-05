"""Direction-consistency validation between transcript text and model output."""

from __future__ import annotations

import logging
import re
from typing import FrozenSet

from models.signal_models import GeminiAnalysisResult

logger = logging.getLogger(__name__)

_BULLISH_KEYWORDS: FrozenSet[str] = frozenset(
    {
        "beat",
        "exceeded",
        "record",
        "growth",
        "raised",
        "guidance",
        "outperformed",
        "accelerating",
        "expanding",
        "profitable",
        "momentum",
        "demand",
        "strong",
        "robust",
        "solid",
        "raise",
        "upgrade",
        "positive",
        "upside",
        "surge",
        "breakout",
        "outperform",
    }
)

_BEARISH_KEYWORDS: FrozenSet[str] = frozenset(
    {
        "miss",
        "missed",
        "declined",
        "disappointing",
        "lowered",
        "below",
        "headwinds",
        "challenging",
        "uncertain",
        "weakness",
        "decelerate",
        "loss",
        "cut",
        "reduce",
        "layoff",
        "restructure",
        "warning",
        "shortfall",
        "fell",
        "pressure",
        "downside",
        "concern",
        "risk",
    }
)

_NEGATION_PREFIXES = re.compile(
    r"\b(not?|no|never|without|fail(?:ed)?|lack(?:ing)?)\s+",
    re.IGNORECASE,
)
_NEGATION_WINDOW_CHARS = 15


def validate_integrity(
    text_chunk: str,
    result: GeminiAnalysisResult,
) -> tuple[bool, str]:
    """Check whether the declared direction is consistent with the text."""

    lower_text = text_chunk.lower()
    declared_direction = result.direction.upper()

    if result.confidence < 0.30:
        return True, "Integrity validation skipped because confidence is low."

    detected_direction = _detect_direction(lower_text)

    if detected_direction == "UNKNOWN":
        return True, "No strong directional keywords were detected in the text."

    if declared_direction == "NEUTRAL":
        if detected_direction in {"BULLISH", "BEARISH"}:
            logger.debug(
                "Neutral output conflicts with detected text direction=%s magnitude=%.2f",
                detected_direction,
                result.magnitude,
            )
            if result.magnitude < 0.4:
                return True, "Neutral direction allowed because magnitude stayed low."
            return False, f"Declared NEUTRAL but detected {detected_direction} language."
        return True, "Neutral output matches mixed directional language."

    if declared_direction != detected_direction:
        reason = (
            f"Declared direction={declared_direction} differs from "
            f"detected direction={detected_direction}."
        )
        logger.warning("Integrity mismatch: %s", reason)
        return False, reason

    return True, "Declared and detected directions match."


def _detect_direction(lower_text: str) -> str:
    """Return BULLISH, BEARISH, NEUTRAL, or UNKNOWN for the text chunk."""

    negation_spans = [match.span() for match in _NEGATION_PREFIXES.finditer(lower_text)]
    bullish_count = 0
    bearish_count = 0

    for keyword in _BULLISH_KEYWORDS:
        for match in re.finditer(rf"\b{re.escape(keyword)}\b", lower_text):
            if _is_negated(match.start(), negation_spans):
                bearish_count += 1
            else:
                bullish_count += 1

    for keyword in _BEARISH_KEYWORDS:
        for match in re.finditer(rf"\b{re.escape(keyword)}\b", lower_text):
            if _is_negated(match.start(), negation_spans):
                bullish_count += 1
            else:
                bearish_count += 1

    if bullish_count == 0 and bearish_count == 0:
        return "UNKNOWN"

    if bullish_count > bearish_count * 1.5:
        return "BULLISH"
    if bearish_count > bullish_count * 1.5:
        return "BEARISH"
    return "NEUTRAL"


def _is_negated(keyword_start: int, negation_spans: list[tuple[int, int]]) -> bool:
    """Return True when a keyword falls inside the negation look-ahead window."""

    for _span_start, span_end in negation_spans:
        if span_end <= keyword_start <= span_end + _NEGATION_WINDOW_CHARS:
            return True
    return False
