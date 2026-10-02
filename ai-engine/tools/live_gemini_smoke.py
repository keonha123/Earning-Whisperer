"""Opt-in real provider smoke. Default preflight makes no network requests.

No FastAPI app, database, Redis, production collection, or mocked provider is used.
Each real phase runs in a disposable working directory with a hard process timeout.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

FIXTURE = "Revenue grew 20% because customer demand increased. Comp sales grew 5%."
IDENTITY = {"ticker": "SMOKE", "call_id": "synthetic-provider-smoke", "sequence": 0}


def _dependency_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _configuration(env_file: str | None):
    from config import Settings
    from core.external_retriever import resolve_embedding_config
    settings = Settings(_env_file=env_file)
    configs = {scope: resolve_embedding_config(settings, scope=scope) for scope in ("transcript", "external")}
    return settings, configs


def _preflight(settings, configs) -> dict:
    reasons = []
    if not settings.gemini_api_key.strip():
        reasons.append("GEMINI_API_KEY_missing")
    if not _dependency_available("google.genai"):
        reasons.append("google_genai_dependency_missing")
    for scope, config in configs.items():
        if config.provider not in {"gemini", "openai"}:
            reasons.append(f"{scope}_embedding_requires_real_provider")
        if config.provider == "openai":
            if not settings.openai_api_key.strip():
                reasons.append("OPENAI_API_KEY_missing")
            if not _dependency_available("openai"):
                reasons.append("openai_dependency_missing")
    return {"status": "ready_not_executed" if not reasons else "unavailable",
            "network_calls_attempted": False, "reasons": sorted(set(reasons)),
            "generation_model": settings.gemini_primary_model,
            "embedding_configurations": {scope: {"provider": c.provider, "model": c.model,
                "dimension": c.dimension, "version": c.version} for scope, c in configs.items()}}


async def _translation(settings) -> dict:
    from models.transcript_assistant_models import TranscriptTranslateRequest
    from services.transcript_assistant_service import TranscriptAssistantService
    result = await TranscriptAssistantService(settings).translate(TranscriptTranslateRequest(**IDENTITY, text=FIXTURE))
    passed = (result.available and result.text_ko is not None and result.original_text == FIXTURE
              and result.call_id == IDENTITY["call_id"] and result.sequence == 0 and "기존점 매출" in result.text_ko)
    return {"phase": "translation", "status": "passed" if passed else "failed",
            "available": result.available, "source": FIXTURE, "text_ko": result.text_ko,
            "warnings": result.warnings}


async def _qa(settings) -> dict:
    from models.transcript_assistant_models import TranscriptAskRequest
    from services.transcript_assistant_service import TranscriptAssistantService
    result = await TranscriptAssistantService(settings).ask(TranscriptAskRequest(
        ticker=IDENTITY["ticker"], call_id=IDENTITY["call_id"], segment_sequences=[0], segment_texts=[FIXTURE],
        question="매출이 증가한 이유는 무엇인가요?", as_of=datetime.now(UTC)))
    citations_valid = bool(result.citations) and all(
        0 <= citation.evidence_index < len(result.evidence)
        and citation.quote in result.evidence[citation.evidence_index].snippet
        for citation in result.citations)
    passed = result.available and not result.refused and bool(result.answer_ko) and citations_valid
    return {"phase": "qa", "status": "passed" if passed else "failed", "available": result.available,
            "answer_ko": result.answer_ko, "refusal_reason": result.refusal_reason,
            "citations": [item.model_dump() for item in result.citations],
            "evidence_count": len(result.evidence), "warnings": result.warnings}


def _embeddings(settings, scope: str) -> dict:
    from core.external_retriever import build_embedding_provider, resolve_embedding_config
    config = resolve_embedding_config(settings, scope=scope)
    if config.provider not in {"gemini", "openai"}:
        return {"phase": f"embeddings_{scope}", "status": "failed", "reason": "hash_is_not_semantic_verification"}
    provider = build_embedding_provider(provider=config.provider, model=config.model, dimension=config.dimension)
    # A single batch, no production records. Related and unrelated strings have
    # deliberately different topics; this checks one fixture, not model quality.
    vectors = provider.embed_texts([
        "Why did the company's sales increase?",
        "The company's revenue rose because customer demand strengthened.",
        "A gardener watered tulips beside a stone fountain.",
    ])
    valid = len(vectors) == 3 and all(len(v) == config.dimension and all(math.isfinite(x) for x in v) for v in vectors)
    if not valid:
        return {"phase": f"embeddings_{scope}", "status": "failed", "reason": "invalid_vector_shape_or_values"}
    def cosine(a, b):
        denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
        return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0.0
    related, unrelated = cosine(vectors[0], vectors[1]), cosine(vectors[0], vectors[2])
    return {"phase": f"embeddings_{scope}", "status": "passed" if related > unrelated else "failed",
            "provider": provider.name, "model": config.model, "dimension": config.dimension,
            "vector_count": len(vectors), "related_cosine": round(related, 6),
            "unrelated_cosine": round(unrelated, 6)}


def _worker(phase: str) -> int:
    # SDK exception messages may include URLs or request details: never forward
    # them into the report. Report only a fixed category and exception class.
    logging.disable(logging.CRITICAL)
    try:
        settings, _ = _configuration(None)
        if phase == "translation":
            result = asyncio.run(_translation(settings))
        elif phase == "qa":
            result = asyncio.run(_qa(settings))
        else:
            result = _embeddings(settings, phase.removeprefix("embeddings_"))
    except Exception as exc:
        result = {"phase": phase, "status": "failed", "reason": "provider_or_runtime_error", "error_type": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


def _worker_environment(settings) -> dict[str, str]:
    env = dict(os.environ)
    # Explicit values make the subprocess and app's cached get_settings agree.
    # Empty isolated cwd prevents an implicit .env from changing the selection.
    names = ["gemini_api_key", "openai_api_key", "gemini_primary_model", "embedding_provider", "embedding_model",
             "embedding_dimension", "embedding_version", "external_embedding_provider", "external_embedding_model",
             "external_embedding_dimension", "external_embedding_version", "transcript_translation_timeout_seconds",
             "transcript_qa_timeout_seconds"]
    for name in names:
        value = getattr(settings, name)
        env[name.upper()] = "" if value is None else str(value)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Execute real provider calls; may incur provider usage")
    mode.add_argument("--preflight", action="store_true", help="No network requests (default)")
    parser.add_argument("--env-file", help="Explicit optional env file; default reads environment only")
    parser.add_argument("--output", type=Path, help="Optional sanitized JSON report file")
    parser.add_argument("--phase-timeout", type=float, default=30, help="Hard per-process seconds (1–60, default30)")
    parser.add_argument("--worker", choices=["translation", "qa", "embeddings_transcript", "embeddings_external"], help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return _worker(args.worker)
    if not 1 <= args.phase_timeout <= 60:
        parser.error("--phase-timeout must be between 1 and 60 seconds")
    logging.disable(logging.CRITICAL)
    started = time.monotonic()
    try:
        settings, configs = _configuration(args.env_file)
        preflight = _preflight(settings, configs)
    except Exception as exc:
        preflight = {"status": "unavailable", "network_calls_attempted": False,
                     "reasons": ["configuration_or_dependency_error"], "error_type": type(exc).__name__}
    report = {"kind": "live_provider_smoke", "mode": "run" if args.run else "preflight",
              "fixture": "synthetic_earnings_only", "preflight": preflight, "results": [],
              "limitations": ["No audio/STT/backend/UI path is exercised", "One fixture is not a linguistic or financial accuracy benchmark",
                              "External corpus retrieval and production Qdrant are not exercised"]}
    exit_code = 2 if preflight["status"] == "unavailable" else 0
    if args.run and not exit_code:
        phases = ["translation", "qa", "embeddings_transcript"]
        if configs["external"] != configs["transcript"]:
            phases.append("embeddings_external")
        else:
            report["embedding_scope_reuse"] = "external uses the identical tested transcript embedding configuration"
        with tempfile.TemporaryDirectory(prefix="earning-provider-smoke-") as isolated_cwd:
            for phase in phases:
                phase_started = time.monotonic()
                try:
                    completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", phase],
                        cwd=isolated_cwd, env=_worker_environment(settings), capture_output=True, text=True,
                        encoding="utf-8", timeout=args.phase_timeout, check=False)
                    result = json.loads(completed.stdout)
                    if not isinstance(result, dict) or result.get("phase") != phase:
                        raise ValueError("Invalid worker report")
                    if completed.returncode != 0:
                        result["status"] = "failed"
                except subprocess.TimeoutExpired:
                    result = {"phase": phase, "status": "failed", "reason": "hard_process_timeout"}
                except Exception as exc:
                    result = {"phase": phase, "status": "failed", "reason": "worker_report_unavailable", "error_type": type(exc).__name__}
                result["elapsed_seconds"] = round(time.monotonic() - phase_started, 3)
                report["results"].append(result)
        exit_code = 0 if all(item.get("status") == "passed" for item in report["results"]) else 1
    report["status"] = "unavailable" if exit_code == 2 else ("failed" if exit_code else ("passed" if args.run else "ready_not_executed"))
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
