"""평가 CLI.

    python -m eval segments            # 원문에서 고정 세그먼트 파일을 다시 만든다
    python -m eval validate            # 질문셋 검증
    python -m eval run --label baseline [--runs 3] [--judge] [--limit N] [--group G] --yes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

import httpx

from assistant.config import Settings
from assistant.openai_client import OpenAIClient
from eval.dataset import DATASET_PATH, load_dataset, validate_dataset
from eval.judge import judge_item, should_judge
from eval.metrics import summarize, time_violations
from eval.report import write_report
from eval.runner import AssistantRunner
from eval.seed import new_call_id, seed_segments
from eval.transcript import CALL_STARTED_AT, SEGMENTS_PATH, TRANSCRIPT_PATH, build_segments, load_segments, write_segments

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4-mini")
ASSISTANT_URL = os.environ.get("EVAL_ASSISTANT_URL", "http://127.0.0.1:8100")
# 문항당 대략값: 생성(콜 전체 ~1.6만 토큰 입력) $0.002, 채점 $0.004. 실제 비용은 보고서의 usage 로 확인한다.
COST_PER_ITEM = {"generate": 0.002, "judge": 0.004}


def estimate_cost_usd(item_count: int, judge: bool) -> float:
    return item_count * (COST_PER_ITEM["generate"] + (COST_PER_ITEM["judge"] if judge else 0.0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("segments")
    sub.add_parser("validate")
    run = sub.add_parser("run")
    run.add_argument("--label", required=True)
    run.add_argument("--runs", type=int, default=1)
    run.add_argument("--judge", action="store_true")
    run.add_argument("--limit", type=int)
    run.add_argument("--group")
    run.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "segments":
        write_segments(SEGMENTS_PATH, build_segments(json.loads(TRANSCRIPT_PATH.read_text(encoding="utf-8")), CALL_STARTED_AT))
        print(f"세그먼트를 다시 만들었습니다: {SEGMENTS_PATH}")
        return 0

    dataset = load_dataset(DATASET_PATH)
    segments = load_segments(SEGMENTS_PATH)
    errors = validate_dataset(dataset, segments)
    if args.command == "validate":
        print("\n".join(errors) if errors else f"문제 없음: {len(dataset.items)}문항")
        return 1 if errors else 0
    if errors:
        print("질문셋에 문제가 있어 실행하지 않습니다:\n" + "\n".join(errors))
        return 1

    items = [i for i in dataset.items if not args.group or i.group == args.group][: args.limit]
    estimate = estimate_cost_usd(len(items), args.judge) * args.runs
    print(f"{len(items)}문항 × {args.runs}회, 채점 {'켬' if args.judge else '끔'} — 예상 비용 약 ${estimate:.2f} "
          f"(Gemini 임베딩 약 {len(items) * args.runs}회 포함)")
    print("전제: backend 를 AI_ENGINE_FACT_CHECK_ENABLED=false AI_ENGINE_SUMMARY_ENABLED=false "
          "AI_ENGINE_TRANSLATION_ENABLED=false 로 띄웠는지 확인합니다.")
    if not args.yes:
        print("실제로 실행하려면 --yes 를 붙입니다.")
        return 2

    settings = Settings()
    judge_llm = OpenAIClient(model=JUDGE_MODEL, parse_effort="low", stream_effort="none",
                             api_key=settings.openai_api_key) if args.judge else None
    with httpx.Client(timeout=30.0) as http:
        for run_index in range(args.runs):
            call_id = new_call_id()
            seed_segments(http, backend_url=settings.backend_base_url, secret=settings.internal_secret,
                          ticker=dataset.ticker, call_id=call_id, segments=segments)
            runner = AssistantRunner(http, assistant_url=ASSISTANT_URL, secret=settings.internal_secret,
                                     ticker=dataset.ticker, call_id=call_id, segments=segments)
            results = []
            for item in items:
                result = runner.run_item(item)
                results.append(result)
                print(f"  {item.id}: {result.status or result.error}")
            judgments = {}
            if judge_llm is not None:
                for item, result in zip(items, results):
                    if should_judge(item, result):
                        judgments[item.id], _ = asyncio.run(judge_item(judge_llm, item, result))
            summary = summarize(items, results, segments, judgments or None)
            rows = [{"id": i.id, "group": i.group, "expected_status": i.expected_status,
                     "time_violations": time_violations(i, r, segments), **asdict(r),
                     "judgment": judgments[i.id].model_dump() if i.id in judgments else None}
                    for i, r in zip(items, results)]
            label = args.label if args.runs == 1 else f"{args.label}-run{run_index + 1}"
            json_path, md_path = write_report(REPORTS_DIR, label, summary, rows)
            print(f"보고서: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
