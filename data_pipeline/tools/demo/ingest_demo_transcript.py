"""시연용 직전 콜 트랜스크립트 적재 도구.

``parse_factset_transcript.py`` 가 만든 JSON 을 ai-engine 에 넣는다.

기존 도구로는 이 일을 할 수 없다. ``collectors/transcripts/manual_import.py`` 는
평문 ``.txt`` 를 받아 메타데이터를 본문에서 추론하는 경로라 발언 단위 정보를
싣지 못한다. ai-engine 은 ``speaker_turns`` 가 있을 때만 발언 단위로 청크를 쪼개고
(``repositories/qdrant_evidence_repository.py`` 의 ``_speaker_turn_entries``),
직전 콜 대조(``transcript/diff``)는 그 청크를 찾아 쓴다. 발언 정보 없이 넣으면
문서 전체를 길이로만 자른 청크만 남아 대조 품질이 떨어진다.

재색인 도구이기도 하다. 임베딩 설정(provider · 모델 · 차원 · 버전)을 바꾸면 이미
저장된 벡터는 새 설정으로 조회되지 않는다. 적재 시점에 임베딩을 다시 만들기 때문에,
이 명령을 다시 돌리는 것이 곧 재색인이다. 포인트 ID 가 청크 ID 에서 결정되므로
같은 원본·같은 청킹이면 덮어쓴다. 청킹 규칙 자체가 바뀌었다면 옛 청크가 남으므로
``--purge`` 로 먼저 지운다.

사용 예::

    # 로컬 ai-engine 에 적재
    python -m data_pipeline.tools.demo.ingest_demo_transcript \\
        --transcript data_pipeline/data/demo/wmt-2026q1-transcript.json \\
        --ticker WMT --provider factset --provider-id wmt-fy27q1-2026-05-21 \\
        --title "Walmart, Inc. (WMT) Q1 FY2027 Earnings Call" \\
        --published-at 2026-05-21 --fiscal-quarter FY2027Q1

    # 청킹 규칙이 바뀌어 옛 포인트를 지우고 다시 넣을 때
    python -m data_pipeline.tools.demo.ingest_demo_transcript ... \\
        --purge --qdrant-url http://localhost:6333

임베딩 요청량은 청크 수만큼이다. 62발언 트랜스크립트가 68청크였고 Gemini 무료 등급
하루 1,000요청 대비 부담이 없다. 한도는 한국시간 16:00 에 리셋된다.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any

import httpx


logger = logging.getLogger("ingest-demo-transcript")

INGEST_PATH = "/api/v1/integration/collector/earnings-transcripts"
TRANSCRIPT_COLLECTION = "earningwhisperer_transcripts"
# ai-engine 이 document_id 를 만드는 규칙과 같아야 한다
# (services/transcript_ingestion_service.py 의 ingest).
DOCUMENT_ID_FORMAT = "{provider}:{ticker}:{provider_id}"


def build_item(
    *,
    transcript_path: Path,
    text_path: Path | None,
    ticker: str,
    provider: str,
    provider_id: str,
    title: str,
    published_at: str,
    fiscal_quarter: str,
) -> dict[str, Any]:
    """파싱 결과 JSON 을 적재 요청 항목으로 바꾼다."""
    parsed = json.loads(transcript_path.read_text(encoding="utf-8"))
    turns = parsed.get("turns")
    if not isinstance(turns, list) or not turns:
        raise SystemExit(f"turns 가 비어 있습니다: {transcript_path}")

    # 본문은 같은 이름의 .txt 를 기본으로 쓴다. parse_factset_transcript.py 가
    # JSON 과 나란히 떨구는 파일이고, 발언 사이 구분이 원문 그대로 남아 있다.
    if text_path is None:
        text_path = transcript_path.with_suffix(".txt")
    if text_path.exists():
        content = text_path.read_text(encoding="utf-8")
    else:
        logger.warning("본문 파일이 없어 turns 를 이어 붙입니다: %s", text_path)
        content = "\n\n".join(str(turn.get("text") or "") for turn in turns)

    speaker_turns = [
        {
            "speaker": str(turn.get("speaker") or ""),
            "text": str(turn.get("text") or ""),
            "section": turn.get("section"),
        }
        for turn in turns
    ]

    logger.info("발언 %d개, 본문 %d자", len(speaker_turns), len(content))
    return {
        "provider": provider,
        "provider_id": provider_id,
        "ticker": ticker,
        "title": title,
        "published_at": published_at,
        "fiscal_quarter": fiscal_quarter,
        "content": content,
        "speaker_turns": speaker_turns,
    }


def purge(*, qdrant_url: str, collection: str, document_id: str) -> int:
    """해당 문서의 기존 포인트를 지운다.

    적재는 청크 ID 기준으로 덮어쓰므로 보통 필요하지 않다. 청킹 규칙이 바뀌어
    청크 수나 경계가 달라졌을 때만 쓴다 — 그때는 옛 청크가 ID 가 달라 남는다.
    """
    base = qdrant_url.rstrip("/")
    selector = {"filter": {"must": [{"key": "document_id", "match": {"value": document_id}}]}}
    with httpx.Client(timeout=60.0) as client:
        before = client.post(
            f"{base}/collections/{collection}/points/count",
            json={"exact": True, **selector},
        )
        before.raise_for_status()
        count = int(before.json()["result"]["count"])
        if count == 0:
            logger.info("지울 포인트가 없습니다: %s", document_id)
            return 0
        response = client.post(
            f"{base}/collections/{collection}/points/delete?wait=true",
            json=selector,
        )
        response.raise_for_status()
    logger.info("기존 포인트 %d건 삭제: %s", count, document_id)
    return count


def ingest(*, ai_engine_url: str, item: dict[str, Any], timeout: float) -> dict[str, Any]:
    """ai-engine 에 적재한다. 임베딩은 서버가 이 시점에 만든다."""
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{ai_engine_url.rstrip('/')}{INGEST_PATH}",
            json={"items": [item]},
        )
        response.raise_for_status()
        return response.json()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--transcript", required=True, type=Path, help="parse_factset_transcript.py 가 만든 JSON")
    parser.add_argument("--text", type=Path, default=None, help="본문 .txt (기본: --transcript 와 같은 이름)")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--provider", default="factset")
    parser.add_argument("--provider-id", required=True, help="예: wmt-fy27q1-2026-05-21")
    parser.add_argument("--title", required=True)
    parser.add_argument("--published-at", required=True, help="YYYY-MM-DD")
    parser.add_argument("--fiscal-quarter", required=True, help="예: FY2027Q1")
    parser.add_argument("--ai-engine-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=600.0, help="임베딩까지 포함한 응답 대기 (초)")
    parser.add_argument("--purge", action="store_true", help="적재 전에 기존 포인트를 지운다")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="--purge 에만 쓴다")
    parser.add_argument("--collection", default=TRANSCRIPT_COLLECTION, help="--purge 에만 쓴다")
    args = parser.parse_args(argv)

    if not args.transcript.exists():
        logger.error("트랜스크립트 파일이 없습니다: %s", args.transcript)
        return 1

    document_id = DOCUMENT_ID_FORMAT.format(
        provider=args.provider,
        ticker=args.ticker.upper(),
        provider_id=args.provider_id,
    )
    logger.info("document_id = %s", document_id)

    if args.purge:
        purge(qdrant_url=args.qdrant_url, collection=args.collection, document_id=document_id)

    item = build_item(
        transcript_path=args.transcript,
        text_path=args.text,
        ticker=args.ticker.upper(),
        provider=args.provider,
        provider_id=args.provider_id,
        title=args.title,
        published_at=args.published_at,
        fiscal_quarter=args.fiscal_quarter,
    )

    body = ingest(ai_engine_url=args.ai_engine_url, item=item, timeout=args.timeout)
    logger.info(
        "적재 결과: status=%s accepted=%s skipped=%s",
        body.get("status"),
        body.get("accepted_count"),
        body.get("skipped_count"),
    )
    if body.get("warnings"):
        logger.warning("경고: %s", body["warnings"])
    return 0 if body.get("accepted_count") else 1


if __name__ == "__main__":
    sys.exit(main())
