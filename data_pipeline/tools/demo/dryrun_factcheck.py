"""시연 후보 문장 팩트체크 드라이런.

**문장을 먼저 고르고 근거를 맞추는 것이 아니라, 근거를 먼저 넣고 실제 판정을 본 다음
보여줄 구간을 고른다.** 지어내지 않으면서 시연 구성을 통제하는 유일한 방법이다.

이 도구는 트랜스크립트에서 후보 문장을 뽑아 실제 팩트체크 경로(AI Engine 의
``/v1/engine/live-fact-check/sentence``)에 그대로 흘려보내고, 나온 판정을 표로 떨군다.
그 표를 보고 사실확인 · 근거부족 · 사실과다름이 고루 섞이도록 최종 문장을 선별한다.

주의:
    AI Engine 은 ticker 별로 3문장 버퍼를 유지하고 ``sentence_sequence=0`` 에서만
    리셋한다. 따라서 이 도구는 0부터 순서대로 제출해야 하며, 같은 ticker 로 두 번
    돌리려면 0부터 다시 시작해야 한다.

    타임스탬프는 반드시 **콜 시각** 이어야 한다. 현재 시각을 넣으면 그 콜 시점의
    뉴스가 근거 검색 창 밖으로 밀려 전부 근거 부족이 된다.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import sys

import httpx


logger = logging.getLogger("dryrun")

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")

#: 사실 주장이 담길 수 없는 짧은 문장. 후보에서 뺀다.
MIN_SENTENCE_CHARS = 40


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(text) if len(s.strip()) >= MIN_SENTENCE_CHARS]


def candidates(parsed: dict, speakers: set[str] | None, limit: int) -> list[dict]:
    """경영진 발언에서 후보 문장을 뽑는다. 오퍼레이터와 애널리스트 질문은 제외."""
    out: list[dict] = []
    for turn in parsed["turns"]:
        if turn["speaker"] == "Operator":
            continue
        role = str(turn.get("role") or "").lower()
        if any(marker in role for marker in ("analyst", "research", "capital", "securities", "bank", "partners")):
            continue
        if speakers and turn["speaker"] not in speakers:
            continue
        for sentence in split_sentences(turn["text"]):
            out.append({"speaker": turn["speaker"], "role": turn["role"], "text": sentence})
            if len(out) >= limit:
                return out
    return out


def run(parsed_path: Path, out_path: Path, ticker: str, call_epoch: int,
        ai_engine_url: str, limit: int, speakers: set[str] | None) -> None:
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    items = candidates(parsed, speakers, limit)
    logger.info("후보 문장 %d개", len(items))

    results: list[dict] = []
    with httpx.Client(timeout=180.0) as client:
        for index, item in enumerate(items):
            payload = {
                "ticker": ticker,
                "sentence": item["text"],
                "sentence_sequence": index,
                # 실제 콜에서 이 문장이 나왔을 시각. 근거 검색 창의 기준이다.
                "sentence_timestamp": call_epoch + index * 6,
                "is_session_end": index == len(items) - 1,
            }
            response = client.post(f"{ai_engine_url.rstrip('/')}/v1/engine/live-fact-check/sentence", json=payload)
            response.raise_for_status()
            body = response.json()
            status = body.get("status")
            if status != "COMPLETED":
                continue
            for claim in body.get("claims") or []:
                results.append({
                    "batch_start": body.get("batch_start_sequence"),
                    "batch_end": body.get("batch_end_sequence"),
                    "speaker": item["speaker"],
                    "claim": claim.get("claim"),
                    "verdict": claim.get("verdict"),
                    "confidence": claim.get("confidence"),
                    "explanation_ko": claim.get("explanation_ko"),
                    "evidence": [
                        {"source": e.get("source"), "title": e.get("title")}
                        for e in (claim.get("evidence") or [])
                    ],
                })
            logger.info("[%3d/%d] 배치 완료 — 누적 판정 %d건", index + 1, len(items), len(results))

    report = {
        "ticker": ticker,
        "call_epoch": call_epoch,
        "candidate_count": len(items),
        "verdict_counts": _counts(results),
        "candidates": items,
        "results": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("\n판정 분포: %s", report["verdict_counts"])
    logger.info("보고서: %s", out_path)
    for row in results:
        evidence = row["evidence"][0]["source"] if row["evidence"] else "-"
        logger.info("  %-22s %-5.2f %-10s %s",
                    row["verdict"], row["confidence"] or 0.0, evidence, str(row["claim"])[:70])


def _counts(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in results:
        key = str(row.get("verdict") or "?")
        counts[key] = counts.get(key, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parsed", required=True, type=Path, help="parse_transcript 산출물")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--call-started-at", required=True, help="ISO-8601, 예 2026-08-20T13:00:00Z")
    parser.add_argument("--ai-engine-url", default="http://localhost:8000")
    parser.add_argument("--limit", type=int, default=60, help="후보 문장 수 (3의 배수 권장)")
    parser.add_argument("--speakers", default="", help="쉼표 구분. 비우면 전체 경영진")
    args = parser.parse_args(argv)

    call_epoch = int(datetime.fromisoformat(args.call_started_at.replace("Z", "+00:00")).timestamp())
    speakers = {s.strip() for s in args.speakers.split(",") if s.strip()} or None
    run(args.parsed, args.out, args.ticker.upper(), call_epoch, args.ai_engine_url, args.limit, speakers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
