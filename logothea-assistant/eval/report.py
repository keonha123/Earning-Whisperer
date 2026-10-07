"""평가 보고서. 시점 위반과 상태 불일치를 맨 위에 둔다(0이어야 하는 것부터 본다)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def render_markdown(label: str, summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [f"# 평가 보고서 — {label}", ""]
    violations = summary.get("time_violations") or {}
    lines += ["## 시점 위반", ""]
    lines += [f"- {item_id}: {', '.join(markers)}" for item_id, markers in violations.items()] or ["- 없음"]
    lines += ["", "## 요약", "",
              f"- 문항 {summary['count']}개, 오류 {summary['errors']}개",
              f"- 상태 정확도 {_pct(summary['status_accuracy'])}",
              f"- 거절: 적절 {summary['refusals']['appropriate']} / 부적절 {summary['refusals']['inappropriate']} / 놓침 {summary['refusals']['missed']}",
              f"- 근거 재현율 {_pct(summary['evidence_recall'])}, 수치 검증 통과율 {_pct(summary['citation_verified_rate'])}"]
    judge = summary.get("judge")
    if judge:
        lines.append(f"- 채점: 요점 충족 {_pct(judge['key_point_coverage'])}, 반대 진술 {_pct(judge['key_point_contradicted'])}, "
                     f"인용 정밀도 {_pct(judge['citation_precision'])} ({judge['judged_items']}문항)")
    latency = summary["latency_ms"]
    lines += [f"- 지연(ms): 첫 토큰 p50 {latency['first_token_p50']} / p95 {latency['first_token_p95']}, "
              f"완료 p50 {latency['total_p50']} / p95 {latency['total_p95']}",
              f"- 비용: 합계 ${summary['cost_usd']['total']:.4f}, 질문당 ${summary['cost_usd']['per_question']:.5f}",
              "", "## 묶음별", "", "| 묶음 | 문항 | 상태 정확도 | 근거 재현율 |", "|---|---|---|---|"]
    lines += [f"| {group} | {row['count']} | {_pct(row['status_accuracy'])} | {_pct(row['evidence_recall'])} |"
              for group, row in summary["by_group"].items()]
    mismatches = [r for r in rows if r.get("error") or r.get("status") != r.get("expected_status")]
    lines += ["", "## 상태 불일치·오류", ""]
    lines += [f"- {r['id']} ({r['group']}): 기대 {r['expected_status']} / 결과 {r.get('status')}"
              + (f" / 오류 {r['error']['code']}" if r.get("error") else "") for r in mismatches] or ["- 없음"]
    return "\n".join(lines) + "\n"


def write_report(directory: Path, label: str, summary: dict[str, Any], rows: list[dict[str, Any]],
                 today: date | None = None) -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{(today or date.today()).isoformat()}-{label}"
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps({"label": label, "summary": summary, "items": rows}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    md_path.write_text(render_markdown(label, summary, rows), encoding="utf-8")
    return json_path, md_path
