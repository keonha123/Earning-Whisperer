from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


AI_ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ENGINE_ROOT))


FILLER_SENTENCES = [
    "This buffer sentence contains no additional factual claim for verification.",
    "This final buffer sentence is included only to trigger the three sentence fact check batch.",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually fact-check user-provided sentences against collected NVIDIA news.",
    )
    parser.add_argument(
        "sentences",
        nargs="*",
        help="Sentence(s) to fact-check. If omitted, --sentence values or stdin lines are used.",
    )
    parser.add_argument(
        "-s",
        "--sentence",
        action="append",
        default=[],
        help="Sentence to fact-check. Can be repeated.",
    )
    parser.add_argument("--ticker", default="NVDA", help="Ticker to use for the fact-check buffer. Default: NVDA.")
    parser.add_argument("--timestamp", type=int, default=None, help="Unix timestamp for retrieval cutoff. Default: now.")
    parser.add_argument("--sequence-start", type=int, default=0, help="Starting sentence_sequence. Default: 0.")
    parser.add_argument("--lookback-days", type=int, default=2, help="FACT_CHECK_NEWS_LOOKBACK_DAYS override. Default: 2.")
    parser.add_argument("--full", action="store_true", help="Print the full LiveFactCheckBatchResponse JSON.")
    parser.add_argument(
        "--respect-env",
        action="store_true",
        help="Do not override vector/embedding env defaults. Use the current .env/environment exactly.",
    )
    return parser.parse_args()


def _collect_sentences(args: argparse.Namespace) -> list[str]:
    sentences = [*args.sentence, *args.sentences]
    if not sentences and not sys.stdin.isatty():
        sentences = [line.strip() for line in sys.stdin if line.strip()]
    if not sentences:
        entered = input("Enter a sentence to fact-check against NVDA news: ").strip()
        if entered:
            sentences.append(entered)
    normalized = [" ".join(sentence.split()) for sentence in sentences if sentence and sentence.strip()]
    if not normalized:
        raise SystemExit("No sentence provided.")
    return normalized


def _apply_runtime_env(args: argparse.Namespace) -> None:
    if not args.respect_env:
        defaults = {
            "VECTOR_STORE_BACKEND": "qdrant",
            "QDRANT_URL": "http://localhost:6333",
            "QDRANT_PATH": "",
            "QDRANT_COLLECTION_NAME": "earningwhisperer_evidence",
            "EMBEDDING_PROVIDER": "openai",
            "EMBEDDING_MODEL": "text-embedding-3-small",
            "EMBEDDING_DIMENSION": "256",
            "EXTERNAL_EMBEDDING_PROVIDER": "openai",
            "EXTERNAL_EMBEDDING_MODEL": "text-embedding-3-small",
            "EXTERNAL_EMBEDDING_DIMENSION": "256",
            "EXTERNAL_EMBEDDING_VERSION": "openai-text-embedding-3-small-256-v1",
            "FACT_CHECK_RETRIEVAL_TIMEOUT_SECONDS": "10",
            "FACT_CHECK_EXTRACTION_TIMEOUT_SECONDS": "15",
            "FACT_CHECK_LLM_TIMEOUT_SECONDS": "20",
        }
        for key, value in defaults.items():
            os.environ[key] = value
    os.environ["FACT_CHECK_NEWS_LOOKBACK_DAYS"] = str(max(1, args.lookback_days))


def _batched_with_fillers(sentences: list[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    for start in range(0, len(sentences), 3):
        batch = sentences[start : start + 3]
        filler_index = 0
        while len(batch) < 3:
            batch.append(FILLER_SENTENCES[filler_index % len(FILLER_SENTENCES)])
            filler_index += 1
        batches.append(batch)
    return batches


def _compact_response(response: Any) -> dict[str, Any]:
    return {
        "ticker": response.ticker,
        "status": str(response.status),
        "batch_start_sequence": response.batch_start_sequence,
        "batch_end_sequence": response.batch_end_sequence,
        "claim_count": len(response.claims),
        "extraction_llm_used": response.extraction_llm_used,
        "verification_llm_used": response.verification_llm_used,
        "warnings": response.warnings,
        "claims": [
            {
                "source_text": claim.source_text,
                "claim": claim.claim,
                "verdict": str(claim.verdict),
                "confidence": claim.confidence,
                "reason_code": str(claim.reason_code),
                "retrieved_count": claim.retrieved_count,
                "accepted_count": claim.accepted_count,
                "evidence": [
                    {
                        "title": evidence.title,
                        "url": evidence.url,
                        "relevance_score": evidence.relevance_score,
                    }
                    for evidence in claim.evidence
                ],
                "explanation_ko": claim.explanation_ko,
            }
            for claim in response.claims
        ],
    }


async def _run() -> None:
    args = _parse_args()
    sentences = _collect_sentences(args)
    _apply_runtime_env(args)

    from models.live_fact_check_models import LiveFactCheckSentenceRequest
    from services.live_news_fact_check_service import LiveNewsFactCheckService

    ticker = args.ticker.strip().upper() or "NVDA"
    timestamp = args.timestamp or int(time.time())
    sequence = max(0, args.sequence_start)
    service = LiveNewsFactCheckService()

    print(
        json.dumps(
            {
                "ticker": ticker,
                "input_sentence_count": len(sentences),
                "note": "Fact-check runs after every 3 submitted sentences; short input is padded with neutral filler sentences.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    for batch_index, batch in enumerate(_batched_with_fillers(sentences), start=1):
        response = None
        for sentence in batch:
            response = await service.submit_sentence(
                LiveFactCheckSentenceRequest(
                    ticker=ticker,
                    sentence=sentence,
                    sentence_sequence=sequence,
                    sentence_timestamp=timestamp,
                )
            )
            sequence += 1

        assert response is not None
        payload = response.model_dump(mode="json") if args.full else _compact_response(response)
        print(f"\n=== FACT CHECK BATCH {batch_index} ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_run())
