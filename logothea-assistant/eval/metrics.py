"""코드로 재는 평가 지표. LLM 채점 결과(judgments)가 있으면 함께 요약한다."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from eval.dataset import EvalItem
from eval.runner import ItemResult
from eval.transcript import EvalSegment

# 100만 토큰당 달러(2026-10 공식 가격). cached 입력 할인은 반영하지 않아 비용을 높게 잡는 쪽이다.
PRICE_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-6-luna": {"input": 0.10, "output": 0.50},
}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return float(ordered[low])
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def cost_usd(usage: dict[str, int], model: str) -> float:
    price = PRICE_PER_MILLION[model]
    return (usage.get("input_tokens", 0) * price["input"] + usage.get("output_tokens", 0) * price["output"]) / 1_000_000


def time_violations(item: EvalItem, result: ItemResult, segments: list[EvalSegment]) -> list[str]:
    as_of_epoch = segments[item.as_of_sequence].timestamp
    violations: list[str] = []
    for citation in result.citations:
        if citation.get("type") == "segment" and citation.get("ref") is not None:
            if int(citation["ref"]) > item.as_of_sequence:
                violations.append(citation["marker"])
        elif citation.get("type") == "news" and citation.get("published_at") is not None:
            if int(citation["published_at"]) > as_of_epoch:
                violations.append(citation["marker"])
    return violations


def evidence_recall(item: EvalItem, result: ItemResult) -> float | None:
    if not item.gold_sequences:
        return None
    cited = {int(c["ref"]) for c in result.citations if c.get("type") == "segment" and c.get("ref") is not None}
    return len(cited & set(item.gold_sequences)) / len(item.gold_sequences)


def summarize(items: list[EvalItem], results: list[ItemResult], segments: list[EvalSegment],
              judgments: dict[str, Any] | None = None, model: str = "gpt-6-luna") -> dict[str, Any]:
    by_id = {r.item_id: r for r in results}
    pairs = [(i, by_id[i.id]) for i in items if i.id in by_id]

    correct = [(i, r) for i, r in pairs if r.error is None and r.status == i.expected_status]
    refusals = {"appropriate": 0, "inappropriate": 0, "missed": 0}
    for i, r in pairs:
        if r.status == "refused" and i.expected_status == "refused":
            refusals["appropriate"] += 1
        elif r.status == "refused":
            refusals["inappropriate"] += 1
        elif i.expected_status == "refused":
            refusals["missed"] += 1

    recalls = [v for i, r in pairs if (v := evidence_recall(i, r)) is not None]
    citations = [c for _, r in pairs for c in r.citations]
    violations = {i.id: v for i, r in pairs if (v := time_violations(i, r, segments))}
    ok = [r for _, r in pairs if r.error is None]
    costs = [cost_usd(r.usage, model) for _, r in pairs if r.usage]

    groups: dict[str, list[tuple[EvalItem, ItemResult]]] = defaultdict(list)
    for i, r in pairs:
        groups[i.group].append((i, r))
    by_group = {
        group: {
            "count": len(rows),
            "status_accuracy": sum(1 for i, r in rows if r.error is None and r.status == i.expected_status) / len(rows),
            "evidence_recall": _mean([v for i, r in rows if (v := evidence_recall(i, r)) is not None]),
        }
        for group, rows in sorted(groups.items())
    }

    summary: dict[str, Any] = {
        "count": len(pairs),
        "errors": sum(1 for _, r in pairs if r.error is not None),
        "status_accuracy": len(correct) / len(pairs) if pairs else 0.0,
        "refusals": refusals,
        "evidence_recall": _mean(recalls),
        "citation_verified_rate": (sum(1 for c in citations if c.get("verified")) / len(citations)) if citations else None,
        "time_violations": violations,
        "latency_ms": {
            "first_token_p50": percentile([r.first_token_ms for r in ok if r.first_token_ms is not None], 0.5),
            "first_token_p95": percentile([r.first_token_ms for r in ok if r.first_token_ms is not None], 0.95),
            "total_p50": percentile([r.total_ms for r in ok], 0.5),
            "total_p95": percentile([r.total_ms for r in ok], 0.95),
        },
        "cost_usd": {"total": sum(costs), "per_question": (sum(costs) / len(costs)) if costs else 0.0},
        "by_group": by_group,
    }
    if judgments:
        points = [p.verdict for j in judgments.values() for p in j.points]
        cites = [c.supported for j in judgments.values() for c in j.citations]
        summary["judge"] = {
            "judged_items": len(judgments),
            "key_point_coverage": (points.count("present") / len(points)) if points else None,
            "key_point_contradicted": (points.count("contradicted") / len(points)) if points else None,
            "citation_precision": (sum(cites) / len(cites)) if cites else None,
        }
    return summary


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
