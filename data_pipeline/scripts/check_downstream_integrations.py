"""Check or send a synthetic transcript through configured downstream services.

The default mode only checks health endpoints. ``--send`` performs an explicit,
identifiable EWTEST delivery through the same durable outbox used by STT.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

import httpx

from data_pipeline import database
from data_pipeline.config import load_project_env
from data_pipeline.stt_worker.take import SttConfig, TranscriptEmitter


def _health_check(client: httpx.Client, base_url: str, paths: tuple[str, ...]) -> dict[str, object]:
    errors: list[str] = []
    for path in paths:
        try:
            response = client.get(f"{base_url.rstrip('/')}{path}")
            if 200 <= response.status_code < 300:
                return {"ok": True, "url": f"{base_url.rstrip('/')}{path}", "status": response.status_code}
            errors.append(f"{path}:HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            errors.append(f"{path}:{exc.__class__.__name__}")
    return {"ok": False, "errors": errors}


def _config(args: argparse.Namespace) -> SttConfig:
    return SttConfig(
        ticker="EWTEST",
        call_id="EWTEST-INTEGRATION-CHECK",
        input_kind="file",
        input_source="/tmp/ewtest-unused.wav",
        input_format="wav",
        ffmpeg_bin="ffmpeg",
        model_name="tiny",
        device="cpu",
        compute_type="int8",
        cpu_threads=1,
        beam_size=1,
        language="en",
        vad_filter=True,
        read_bytes=64000,
        reads_per_emit=1,
        max_chunks=1,
        ai_engine_url=args.ai_engine_url,
        backend_url=args.backend_url,
        internal_secret=args.internal_secret,
        send_to_ai_engine=not args.skip_ai,
        send_to_backend=not args.skip_backend,
        archive_transcripts=False,
        http_timeout_seconds=args.timeout,
        resolve_media_url=False,
        preflight_audio_file=None,
        preflight_report_file=None,
        preflight_required=False,
        preflight_keep_audio=False,
    )


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    parser = argparse.ArgumentParser(description="Verify data_pipeline downstream integrations.")
    parser.add_argument("--send", action="store_true", help="Queue and send one EWTEST transcript segment.")
    parser.add_argument("--ai-engine-url", default=os.getenv("AI_ENGINE_URL", "http://localhost:8000"))
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://localhost:8082"))
    parser.add_argument("--internal-secret", default=os.getenv("INTERNAL_SECRET", ""))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--skip-ai", action="store_true")
    parser.add_argument("--skip-backend", action="store_true")
    args = parser.parse_args(argv)
    args.timeout = max(1.0, args.timeout)

    health: dict[str, object] = {}
    with httpx.Client(timeout=args.timeout) as client:
        if not args.skip_ai:
            health["ai_engine"] = _health_check(client, args.ai_engine_url, ("/health/live", "/health"))
        if not args.skip_backend:
            health["backend"] = _health_check(client, args.backend_url, ("/actuator/health", "/health"))

    result: dict[str, object] = {"health": health, "sent": False}
    if args.send:
        if not args.skip_backend and not args.internal_secret:
            result["error"] = "--internal-secret or INTERNAL_SECRET is required for backend delivery"
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 2
        config = _config(args)
        emitter = TranscriptEmitter(config)
        payload = {
            "ticker": "EWTEST",
            "call_id": f"EWTEST-INTEGRATION-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "text_chunk": "Earning Whisperer downstream integration smoke test.",
            "sequence": 0,
            "timestamp": int(time.time()),
            "is_final": True,
        }
        if not args.skip_ai:
            emitter._queue_delivery(payload, "ai_engine")
        if not args.skip_backend:
            emitter._queue_delivery(
                {
                    "ticker": "EWTEST",
                    "call_id": payload["call_id"],
                    "sequence": 0,
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": payload["text_chunk"],
                    "speaker": None,
                    "timestamp": payload["timestamp"],
                    "is_session_end": True,
                },
                "backend",
            )
        with httpx.Client(timeout=args.timeout) as client:
            result["outbox"] = emitter._flush_outbox(client, limit=10)
        result["sent"] = True
        result["call_id"] = payload["call_id"]

    print(json.dumps(result, ensure_ascii=True, indent=2))
    health_ok = all(bool(value.get("ok")) for value in health.values() if isinstance(value, dict))
    return 0 if health_ok and (not args.send or bool(result.get("outbox", {}).get("failed", 0)) is False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
