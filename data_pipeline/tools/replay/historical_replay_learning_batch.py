from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from ... import database
    from ...stt_worker.manager import STTWorkerManager
    from ..learning.webcast_learning_batch import (
        capture_environment,
        classify_probe_outcome,
        effective_audio_probe_timeout_seconds,
        is_future_event,
    )
except ImportError:  # Allows `python data_pipeline/historical_replay_learning_batch.py`.
    from data_pipeline import database
    from data_pipeline.stt_worker.manager import STTWorkerManager
    from data_pipeline.tools.learning.webcast_learning_batch import (
        capture_environment,
        classify_probe_outcome,
        effective_audio_probe_timeout_seconds,
        is_future_event,
    )


def resolved_player_url(
    manager: STTWorkerManager,
    call: dict[str, Any],
    capture_env: dict[str, str],
) -> str | None:
    """Read the browser's final player URL for reuse on the next replay attempt."""
    runtime = manager.build_isolated_capture_environment(call, capture_env)
    for key in (
        "WEBCAST_ACTIVE_PLAYER_URL_FILE",
        "WEBCAST_LAST_TARGET_URL_FILE",
    ):
        path = str(runtime.get(key) or "").strip()
        if not path:
            continue
        if path.startswith("/app/"):
            path = str(Path(__file__).resolve().parents[3] / path.removeprefix("/app/"))
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
    return None


async def run_batch(args: argparse.Namespace) -> int:
    recovered = database.recover_stale_historical_replay_targets()
    if recovered:
        print(f"[ReplayLearning] recovered {recovered} interrupted probes", flush=True)

    requested_tickers = {
        ticker.strip().upper()
        for ticker in args.tickers.split(",")
        if ticker.strip()
    }
    requested_source_kinds = {
        source_kind.strip().lower()
        for source_kind in args.source_kinds.split(",")
        if source_kind.strip()
    }
    requested_statuses = {
        status.strip().lower()
        for status in args.statuses.split(",")
        if status.strip()
    }
    filtered_request = bool(
        requested_tickers or requested_source_kinds or requested_statuses
    )
    targets = database.get_historical_replay_targets(
        limit=None if filtered_request else args.limit,
        include_registration_required=args.allow_registration_submission,
        include_auth_required=args.retry_auth_required,
        auth_required_only=args.auth_required_only,
        registration_required_only=args.registration_required_only,
    )
    if requested_tickers:
        targets = [
            target
            for target in targets
            if str(target["ticker"]).upper() in requested_tickers
        ]
    if requested_source_kinds:
        targets = [
            target
            for target in targets
            if str(target.get("source_kind") or "").lower() in requested_source_kinds
        ]
    if requested_statuses:
        targets = [
            target
            for target in targets
            if str(target.get("status") or "").lower() in requested_statuses
        ]
    if filtered_request and args.limit is not None:
        targets = targets[: max(1, args.limit)]

    future_targets = [target for target in targets if is_future_event(target)]
    if future_targets:
        targets = [target for target in targets if not is_future_event(target)]
        for target in future_targets:
            database.record_historical_replay_outcome(
                target,
                status="not_live_yet",
                error="future event evidence skipped during historical replay learning",
                output="future event evidence skipped during historical replay learning",
            )
        print(
            f"[ReplayLearning] skipped {len(future_targets)} future event targets; "
            "historical replay verification only uses past events",
            flush=True,
        )
    if not targets:
        print("[ReplayLearning] No unverified replay candidates available.")
        return 0

    targets_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        targets_by_ticker[str(target["ticker"]).upper()].append(target)

    print(
        f"[ReplayLearning] {len(targets)} replay candidates across "
        f"{len(targets_by_ticker)} tickers, concurrency={args.concurrency}, "
        f"audio_wait={args.audio_wait_seconds}s"
    )
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    manager = STTWorkerManager()
    results: Counter[str] = Counter()
    skipped = 0
    capture_env = {
        **capture_environment(args),
        "WEBCAST_LIFECYCLE": "replay",
    }
    timeout = effective_audio_probe_timeout_seconds(
        configured_timeout_seconds=args.timeout_seconds,
        playback_timeout_seconds=args.playback_timeout_seconds,
        warmup_seconds=args.warmup_seconds,
        audio_wait_seconds=args.audio_wait_seconds,
    )

    async def probe_ticker(
        ticker_targets: list[dict[str, Any]],
    ) -> list[str]:
        nonlocal skipped
        ticker_results: list[str] = []
        async with semaphore:
            for target in ticker_targets:
                if not database.claim_historical_replay_target(
                    target,
                    cooldown_minutes=0 if args.force else args.cooldown_minutes,
                ):
                    skipped += 1
                    continue

                call = {
                    "id": target["call_id"],
                    "ticker": target["ticker"],
                    "ir_url": target["target_url"],
                    "call_year": target.get("call_year"),
                    "quarter": target.get("quarter"),
                }
                audible, error = await manager.probe_webcast_url(
                    call,
                    capture_env=capture_env,
                    timeout_seconds=timeout,
                )
                status = classify_probe_outcome(audible, error)
                database.record_historical_replay_outcome(
                    target,
                    status=status,
                    error=error,
                    output=error,
                )
                resolved_url = resolved_player_url(manager, call, capture_env)
                original_url = str(target.get("target_url") or "").rstrip("/")
                if resolved_url and resolved_url.rstrip("/") != original_url:
                    database.save_historical_replay_targets(
                        {
                            "call_id": target.get("call_id"),
                            "ticker": target["ticker"],
                            "call_year": target.get("call_year"),
                            "quarter": target.get("quarter"),
                            "earning_at": target.get("earning_at"),
                        },
                        [
                            {
                                "target_url": resolved_url,
                                "source_kind": "browser_resolved",
                                "source_title": (
                                    f"{target['ticker']} browser-resolved playback page"
                                ),
                                "source_snippet": (
                                    f"Reached from {target['target_url']} during browser replay."
                                ),
                                "provider_domain": urlparse(resolved_url).hostname or "",
                            }
                        ],
                    )
                    print(
                        f"[ReplayLearning] {target['ticker']} saved closer playback entrypoint: "
                        f"{resolved_url}",
                        flush=True,
                    )
                ticker_results.append(status)
                print(
                    f"[ReplayLearning] {target['ticker']} {status} "
                    f"provider={target.get('provider_domain') or 'unknown'}"
                    + (f" detail={error[:180]}" if error else ""),
                    flush=True,
                )
                if audible:
                    break
        return ticker_results

    tasks = [
        asyncio.create_task(probe_ticker(ticker_targets))
        for ticker_targets in targets_by_ticker.values()
    ]
    for task in asyncio.as_completed(tasks):
        for status in await task:
            results[status] += 1

    summary = ", ".join(f"{status}={count}" for status, count in sorted(results.items())) or "no probes"
    print(f"[ReplayLearning] batch complete: {summary}; skipped={skipped}")
    print(f"[ReplayLearning] persisted summary: {database.get_historical_replay_summary()}")
    print(f"[ReplayLearning] coverage: {database.get_historical_replay_coverage_summary()}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audio-verify historical earnings-webcast replay candidates.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated tickers to verify instead of every pending replay candidate.",
    )
    parser.add_argument(
        "--source-kinds",
        default="",
        help="Comma-separated replay source kinds to verify, such as ir_entrypoint.",
    )
    parser.add_argument(
        "--statuses",
        default="",
        help="Comma-separated persisted target statuses to verify, such as no_candidate,error.",
    )
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("WEBCAST_REPLAY_CONCURRENCY", "1")))
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=int(os.getenv("WEBCAST_REPLAY_COOLDOWN_MINUTES", "10080")),
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-registration-submission",
        action="store_true",
        help="Allow configured profile fields to be submitted to third-party webcast forms.",
    )
    parser.add_argument(
        "--retry-auth-required",
        action="store_true",
        help="Retry targets previously blocked on Q4 or webcast authentication.",
    )
    parser.add_argument(
        "--auth-required-only",
        action="store_true",
        help="Verify only targets currently classified as requiring Q4 authentication.",
    )
    parser.add_argument(
        "--registration-required-only",
        action="store_true",
        help="Verify only targets currently blocked on a webcast registration form.",
    )
    parser.add_argument(
        "--disable-generalized-learning",
        action="store_true",
        help="Use the pre-generalization domain heuristic for an A/B comparison.",
    )
    parser.add_argument(
        "--audio-wait-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_REPLAY_AUDIO_WAIT_SECONDS", "20")),
    )
    parser.add_argument(
        "--audio-probe-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_LEARNING_AUDIO_PROBE_SECONDS", "2")),
    )
    parser.add_argument(
        "--warmup-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_REPLAY_WARMUP_SECONDS", "3")),
    )
    parser.add_argument(
        "--playback-timeout-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS", "90")),
    )
    parser.add_argument(
        "--audio-min-db",
        type=float,
        default=float(os.getenv("DATE_STREAM_AUDIO_MIN_DB", "-55")),
    )
    parser.add_argument("--timeout-seconds", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_batch(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
