"""여러 보고서(JSON)의 핵심 지표를 모아 평균과 편차를 낸다. 파일을 쓰지 않는다."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

METRICS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "status_accuracy": lambda s: s.get("status_accuracy"),
    "evidence_recall": lambda s: s.get("evidence_recall"),
    "numeric_citation_check_rate": lambda s: s.get("numeric_citation_check_rate"),
    "key_point_coverage": lambda s: (s.get("judge") or {}).get("key_point_coverage"),
    "citation_precision": lambda s: (s.get("judge") or {}).get("citation_precision"),
    "first_token_p50": lambda s: (s.get("latency_ms") or {}).get("first_token_p50"),
    "cost_per_question": lambda s: (s.get("cost_usd") or {}).get("per_question"),
}


def aggregate(summaries: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    """지표별 평균과 모표준편차. 값이 하나도 없으면 None."""
    result: dict[str, dict[str, float | None]] = {}
    for name, getter in METRICS.items():
        values = [float(v) for s in summaries if (v := getter(s)) is not None]
        if not values:
            result[name] = {"mean": None, "std": None}
            continue
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        result[name] = {"mean": mean, "std": std}
    return result


def load_summaries(paths: list[Path]) -> list[dict[str, Any]]:
    return [json.loads(Path(p).read_text(encoding="utf-8"))["summary"] for p in paths]
