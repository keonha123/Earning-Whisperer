from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter, defaultdict
from typing import Any

try:
    from ... import database
    from ...stt_worker.manager import STTWorkerManager
    from ..learning.webcast_learning_batch import (
        capture_environment,
        classify_probe_outcome,
        is_future_event,
    )
except ImportError:  # Allows `python data_pipeline/historical_replay_learning_batch.py`.
    from data_pipeline import database
    from data_pipeline.stt_worker.manager import STTWorkerManager
    from data_pipeline.tools.learning.webcast_learning_batch import (
        capture_environment,
        classify_probe_outcome,
        is_future_event,
    )


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
    filtered_request = bool(requested_tickers or requested_source_kinds)
    targets = database.get_historical_replay_targets(
        limit=None if filtered_request else args.limit,
        include_registration_required=args.allow_registration_submission,
        include_auth_required=args.retry_auth_required,
        auth_required_only=args.auth_required_only,
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
    if filtered_request and args.limit is not None:
        targets = targets[: max(1, args.limit)]

    future_targets = [target for target in targets if is_future_event(target)]
    if future_targets:
        targets = [target for target in targets if not is_future_event(target)]
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
    timeout = (
        args.timeout_seconds
        or args.playback_timeout_seconds
        + args.warmup_seconds
        + args.audio_wait_seconds
        + 15
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
