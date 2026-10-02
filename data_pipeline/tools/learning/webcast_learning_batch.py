from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from ... import database
    from ...stt_worker.manager import STTWorkerManager
except ImportError:  # Allows `python data_pipeline/webcast_learning_batch.py`.
    from data_pipeline import database
    from data_pipeline.stt_worker.manager import STTWorkerManager

REPO_ROOT = Path(__file__).resolve().parents[3]

ACCESS_BLOCKED_TOKENS = (
    "page access blocked",
    "access denied",
    "player access was denied",
    "code: 1011",
    "code 1011",
    "captcha",
    "forbidden",
    "verify you are human",
    "performing security verification",
    "checking your browser",
    "unusual traffic",
    "this request was blocked by our security service",
    "error 15",
    "powered by imperva",
)


def effective_audio_probe_timeout_seconds(
    *,
    configured_timeout_seconds: int | None,
    playback_timeout_seconds: int,
    warmup_seconds: int,
    audio_wait_seconds: int,
) -> int:
    """Return an outer timeout that leaves room for direct-media fallback.

    The browser route observes the virtual audio device once.  When a direct
    media URL is available but that first route is silent, the capture runner
    starts a second isolated PulseAudio observation.  Every batch entrypoint
    must leave room for both windows; otherwise a valid fallback is reported
    as a timeout before it can finish.
    """
    minimum = (
        max(1, int(playback_timeout_seconds))
        + max(0, int(warmup_seconds))
        + max(1, int(audio_wait_seconds)) * 2
        + 30
    )
    configured = int(configured_timeout_seconds or 0)
    return max(configured, minimum) if configured else minimum


def classify_probe_outcome(audible: bool, error: str | None) -> str:
    if audible:
        return "audible"
    message = (error or "").lower()
    if _is_capture_runtime_error(message):
        return "capture_runtime_failed"
    if "not_live_yet" in message or "not yet available" in message:
        return "not_live_yet"
    if "resource_not_found" in message or "resource you have requested cannot be found" in message:
        return "not_found"
    if (
        "expired_event" in message
        or "expired.mp4" in message
        or "recording" in message and "not available" in message
    ):
        return "expired"
    if any(token in message for token in ACCESS_BLOCKED_TOKENS):
        return "blocked"
    if "registration_blocked" in message:
        return "blocked"
    if "auth_required" in message or "password/q4_password is missing" in message:
        return "auth_required"
    if "registration_required" in message:
        return "registration_required"
    if "webcast button not found" in message or "no candidate" in message:
        return "no_candidate"
    if any(token in message for token in ("audio_not_detected", "webcast_exited_before_audio", "audio was not detected")):
        return "no_audio"
    return "error"


def diagnose_probe_error(error: str | None) -> str:
    """Extract a retryable root cause from the browser/audio wrapper output."""
    message = (error or "").lower()
    if _is_capture_runtime_error(message):
        return "capture_runtime_failed"
    if any(token in message for token in ACCESS_BLOCKED_TOKENS):
        return "blocked"
    if "not_live_yet" in message or "not yet available" in message:
        return "not_live_yet"
    if "resource_not_found" in message or "resource you have requested cannot be found" in message:
        return "not_found"
    if (
        "expired_event" in message
        or "expired.mp4" in message
        or ("recording" in message and "not available" in message)
    ):
        return "expired"
    if "auth_required" in message or "password/q4_password is missing" in message:
        return "auth_required"
    if "registration_blocked" in message:
        return "blocked"
    if "registration form handling failed" in message or "registration form remained visible" in message:
        return "registration_failed"
    if "invalid_fields=" in message or "registration requestsubmit" in message:
        return "registration_failed"
    if (
        "webcast opened but playback was not detected" in message
        or "webcast_exited_before_playback_ready" in message
    ):
        return "playback_activation_failed"
    if "no active media or playable control found" in message or "webcast button not found" in message:
        return "player_control_missing"
    if "learned recipe did not replay" in message:
        return "learned_recipe_replay_failed"
    if "click target settle timed out" in message or "page.goto: timeout" in message:
        return "navigation_timeout"
    if "attempting click action" in message or "scroll_into_view_if_needed" in message:
        return "player_interaction_timeout"
    if "playback_ready_timed_out" in message or "waiting_for_playback_ready" in message:
        return "playback_ready_timeout"
    if "download is starting" in message:
        return "download_response"
    if "no such file or directory: 'docker'" in message:
        return "capture_runtime_failed"
    if "audio probe timed out" in message:
        return "audio_probe_timeout"
    if "replay probe terminated" in message:
        return "probe_interrupted"
    if "audio probe failed" in message:
        return "audio_probe_unknown"
    return "unknown_error"


def _is_capture_runtime_error(message: str) -> bool:
    """Keep audio-container startup failures out of site-learning categories."""
    return any(
        token in message
        for token in (
            "module initialization failed",
            "daemon startup failed",
            "pulseaudio server did not start",
            "connection failure: connection refused",
        )
    )


def capture_environment(args: argparse.Namespace) -> dict[str, str]:
    playback_timeout_seconds = int(getattr(args, "playback_timeout_seconds", 90))
    environment = {
        "WEBCAST_HEADED": "true",
        "WEBCAST_VNC_ENABLED": "false",
        "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": (
            "true" if getattr(args, "allow_registration_submission", False) else "false"
        ),
        "WEBCAST_REGISTRATION_PREVIEW_ONLY": (
            "true" if getattr(args, "registration_preview_only", False) else "false"
        ),
        "WEBCAST_GENERALIZED_LEARNING_ENABLED": (
            "false" if getattr(args, "disable_generalized_learning", False) else "true"
        ),
        "WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS": str(playback_timeout_seconds),
        "WEBCAST_AUDIO_WARMUP_SECONDS": str(args.warmup_seconds),
        "WEBCAST_HOLD_SECONDS": str(args.warmup_seconds + args.audio_wait_seconds + 15),
        "DATE_STREAM_AUDIO_WAIT_SECONDS": str(args.audio_wait_seconds),
        "DATE_STREAM_AUDIO_PROBE_SECONDS": str(args.audio_probe_seconds),
        "DATE_STREAM_AUDIO_MIN_DB": str(args.audio_min_db),
    }
    approval_file = str(getattr(args, "registration_approval_file", "") or "").strip()
    if approval_file:
        approval_path = Path(approval_file).expanduser()
        if not approval_path.is_absolute():
            approval_path = REPO_ROOT / approval_path
        try:
            relative_path = approval_path.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            relative_path = None
        environment["WEBCAST_REGISTRATION_APPROVAL_FILE"] = (
            f"/app/{relative_path}" if relative_path is not None else str(approval_path)
        )
    # Keep optional browser diagnostics available inside the isolated capture
    # container without making verbose logging the default for batch runs.
    diagnostics = os.getenv("WEBCAST_REGISTRATION_DIAGNOSTICS", "").strip()
    if diagnostics:
        environment["WEBCAST_REGISTRATION_DIAGNOSTICS"] = diagnostics
    direct_target_navigation_timeout = os.getenv(
        "WEBCAST_DIRECT_TARGET_NAVIGATION_TIMEOUT_SECONDS",
        "",
    ).strip()
    if direct_target_navigation_timeout:
        environment["WEBCAST_DIRECT_TARGET_NAVIGATION_TIMEOUT_SECONDS"] = (
            direct_target_navigation_timeout
        )
    # Reuse the authenticated Q4 browser state captured by visible/manual mode.
    # The probe manager assigns a separate save path per call, so concurrent
    # audits never write back into this shared read-only input state.
    q4_state_path = REPO_ROOT / "data_pipeline" / ".runtime" / "state" / "q4_auth.json"
    if q4_state_path.exists():
        environment["WEBCAST_STORAGE_STATE"] = "/app/data_pipeline/.runtime/state/q4_auth.json"
    return environment


def is_future_event(target: dict[str, Any]) -> bool:
    now_utc = datetime.now(timezone.utc)
    scheduled_at = target.get("scheduled_at_utc")
    if scheduled_at:
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        if scheduled_at > now_utc:
            return True

    earning_at = target.get("earning_at")
    event_timezone = ZoneInfo(os.getenv("DATE_STREAM_WATCH_TIMEZONE", "America/New_York"))
    today = datetime.now(event_timezone).date()
    if earning_at and earning_at.date() > today:
        return True

    # Search results can point at a future event even when the DB call row is
    # stale. Treat an explicit date in the discovery evidence as authoritative
    # for replay learning, so upcoming pages do not consume browser probes.
    evidence = " ".join(
        str(target.get(key) or "")
        for key in ("source_title", "source_snippet", "target_url")
    )
    month_pattern = (
        r"\b(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|"
        r"Sept|Oct|Nov|Dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+20\d{2}\b"
    )
    for match in re.finditer(month_pattern, evidence, re.IGNORECASE):
        normalized = re.sub(r"(\d{1,2})(?:st|nd|rd|th)", r"\1", match.group(0))
        normalized = normalized.replace(",", "")
        parsed = None
        for pattern in ("%B %d %Y", "%b %d %Y"):
            try:
                parsed = datetime.strptime(normalized, pattern).date()
                break
            except ValueError:
                continue
        if parsed and parsed >= today:
            return True
    return False


async def run_batch(args: argparse.Namespace) -> int:
    targets = database.get_webcast_learning_targets(limit=args.limit)
    if not targets:
        print("[UniverseLearning] No IR targets available.")
        return 0

    print(
        f"[UniverseLearning] {len(targets)} targets, concurrency={args.concurrency}, "
        f"audio_wait={args.audio_wait_seconds}s"
    )
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    manager = STTWorkerManager()
    results: Counter[str] = Counter()
    skipped = 0
    capture_env = capture_environment(args)
    timeout = effective_audio_probe_timeout_seconds(
        configured_timeout_seconds=args.timeout_seconds,
        playback_timeout_seconds=args.playback_timeout_seconds,
        warmup_seconds=args.warmup_seconds,
        audio_wait_seconds=args.audio_wait_seconds,
    )

    async def probe(target: dict[str, Any]) -> str | None:
        nonlocal skipped
        async with semaphore:
            if not database.claim_webcast_learning_target(
                target,
                cooldown_minutes=0 if args.force else args.cooldown_minutes,
            ):
                skipped += 1
                return None

            call = {
                "id": target.get("call_id"),
                "ticker": target["ticker"],
                "ir_url": target["target_url"],
                "call_year": target.get("call_year"),
                "quarter": target.get("quarter"),
            }
            if is_future_event(target):
                discovered, error = await manager.learn_webcast_url(call, timeout_seconds=timeout)
                if discovered:
                    status = "not_live_yet"
                else:
                    classified = classify_probe_outcome(False, error)
                    status = classified if classified in {"blocked", "error"} else "not_live_yet"
            else:
                audible, error = await manager.probe_webcast_url(
                    call,
                    capture_env=capture_env,
                    timeout_seconds=timeout,
                )
                status = classify_probe_outcome(audible, error)
        database.record_webcast_learning_target_outcome(
            target,
            status=status,
            error=error,
            output=error,
        )
        print(
            f"[UniverseLearning] {target['ticker']} {status} "
            f"source={target['target_kind']}"
            + (f" detail={error[:180]}" if error else ""),
            flush=True,
        )
        return status

    tasks = [asyncio.create_task(probe(target)) for target in targets]
    for task in asyncio.as_completed(tasks):
        result = await task
        if result:
            results[result] += 1

    summary = ", ".join(f"{status}={count}" for status, count in sorted(results.items())) or "no probes"
    print(f"[UniverseLearning] batch complete: {summary}; skipped={skipped}")
    print(f"[UniverseLearning] persisted summary: {database.get_webcast_learning_summary()}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the full earnings-webcast universe and persist reusable browser recipes."
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit this run; omit for every active stock.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("WEBCAST_LEARNING_CONCURRENCY", "2")),
    )
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=int(os.getenv("WEBCAST_LEARNING_COOLDOWN_MINUTES", "1440")),
    )
    parser.add_argument("--force", action="store_true", help="Ignore the target cooldown for this run.")
    parser.add_argument(
        "--allow-registration-submission",
        action="store_true",
        help="Allow configured profile fields to be submitted to third-party webcast forms.",
    )
    parser.add_argument(
        "--registration-preview-only",
        action="store_true",
        help=(
            "Fill detected registration forms and report redacted destinations/"
            "field names without submitting them."
        ),
    )
    parser.add_argument(
        "--registration-approval-file",
        default="",
        help=(
            "JSON approval manifest; submission is allowed only when the "
            "ticker, destination, prepared fields, and consent state match."
        ),
    )
    parser.add_argument(
        "--disable-generalized-learning",
        action="store_true",
        help="Use the pre-generalization domain heuristic for an A/B comparison.",
    )
    parser.add_argument(
        "--audio-wait-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_LEARNING_AUDIO_WAIT_SECONDS", "15")),
    )
    parser.add_argument(
        "--audio-probe-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_LEARNING_AUDIO_PROBE_SECONDS", "2")),
    )
    parser.add_argument(
        "--warmup-seconds",
        type=int,
        default=int(os.getenv("WEBCAST_LEARNING_WARMUP_SECONDS", "3")),
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
