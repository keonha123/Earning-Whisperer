from __future__ import annotations

import argparse
import asyncio
import os
import threading
import time
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer

from sqlalchemy import text

from ... import database
from .mock_webcast_server import MockWebcastHandler
from ...orchestrator import EarningsOrchestrator


MOCK_TICKER = "EWTEST"
MOCK_CALL_YEAR = 2099
MOCK_QUARTER = "Q4"


def seed_test_call(url: str, *, earning_at: datetime) -> int:
    """Insert one clearly marked, same-day test call for the date watcher."""
    database.ensure_schedule_time_schema()
    with database.engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO stocks (ticker, company_name, sector, ir_url, active)
                VALUES (:ticker, :company_name, :sector, :ir_url, TRUE)
                ON DUPLICATE KEY UPDATE
                    company_name = VALUES(company_name),
                    sector = VALUES(sector),
                    ir_url = VALUES(ir_url),
                    active = TRUE
            """),
            {
                "ticker": MOCK_TICKER,
                "company_name": "Earning Whisperer Local Test",
                "sector": "Test",
                "ir_url": url,
            },
        )
        conn.execute(
            text("""
                INSERT INTO calls (
                    ticker, earning_at, scheduled_at_utc, call_year, quarter, status,
                    time_verification_status
                )
                VALUES (
                    :ticker, :earning_at, :scheduled_at_utc, :call_year, :quarter,
                    'upcoming', 'verified'
                )
                ON DUPLICATE KEY UPDATE
                    earning_at = VALUES(earning_at),
                    scheduled_at_utc = VALUES(scheduled_at_utc),
                    status = 'upcoming',
                    time_verification_status = 'verified',
                    video_url = NULL,
                    stream_probe_status = 'pending',
                    last_stream_probe_at = NULL,
                    last_stream_probe_error = NULL
            """),
            {
                "ticker": MOCK_TICKER,
                "earning_at": earning_at,
                "scheduled_at_utc": earning_at,
                "call_year": MOCK_CALL_YEAR,
                "quarter": MOCK_QUARTER,
            },
        )
        call_id = conn.execute(
            text("""
                SELECT id FROM calls
                WHERE ticker = :ticker AND call_year = :call_year AND quarter = :quarter
            """),
            {
                "ticker": MOCK_TICKER,
                "call_year": MOCK_CALL_YEAR,
                "quarter": MOCK_QUARTER,
            },
        ).scalar_one()
    return int(call_id)


def read_test_result(call_id: int) -> dict:
    with database.engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT id, ticker, status, stream_probe_status,
                       stream_probe_attempts, last_stream_probe_error
                FROM calls WHERE id = :call_id
            """),
            {"call_id": call_id},
        ).mappings().one()
    return dict(row)


def cleanup_test_call(call_id: int) -> None:
    with database.engine.begin() as conn:
        conn.execute(text("DELETE FROM calls WHERE id = :call_id"), {"call_id": call_id})
        conn.execute(text("DELETE FROM stocks WHERE ticker = :ticker"), {"ticker": MOCK_TICKER})


def cleanup_test_data() -> None:
    with database.engine.begin() as conn:
        conn.execute(text("DELETE FROM calls WHERE ticker = :ticker"), {"ticker": MOCK_TICKER})
        conn.execute(text("DELETE FROM stocks WHERE ticker = :ticker"), {"ticker": MOCK_TICKER})


def reset_probe_cooldown_for_test(call_id: int) -> None:
    """Allow a short local test to emulate later scheduler ticks without waiting 15 minutes."""
    with database.engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE calls
                SET last_stream_probe_at = NULL,
                    stream_probe_status = 'pending'
                WHERE id = :call_id
            """),
            {"call_id": call_id},
        )


async def run_e2e(
    port: int,
    *,
    cleanup: bool,
    with_stt: bool,
    scheduled_delay_seconds: float = 0,
    poll_interval_seconds: float = 1,
) -> int:
    url = f"http://127.0.0.1:{port}/"
    scheduled_at = datetime.now().replace(microsecond=0) + timedelta(
        seconds=max(0.0, scheduled_delay_seconds),
    )
    call_id = seed_test_call(url, earning_at=scheduled_at)
    server = ThreadingHTTPServer(("127.0.0.1", port), MockWebcastHandler)
    MockWebcastHandler.posts.clear()
    MockWebcastHandler.set_scheduled_at(scheduled_at if scheduled_delay_seconds > 0 else None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    os.environ.update(
        {
            "WEBCAST_CAPTURE_RUNNER": "container",
            "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "true",
            "WEBCAST_FIRST_NAME": "Test",
            "WEBCAST_LAST_NAME": "User",
            "WEBCAST_COMPANY": "EWTEST",
            "WEBCAST_EMAIL": "ewtest@example.invalid",
            "WEBCAST_INDUSTRY_AFFILIATION": "Other",
            "WEBCAST_LIFECYCLE": "live",
            "DATE_STREAM_WATCH_DAYS_AHEAD": "1",
            "DATE_STREAM_WATCH_BATCH_SIZE": "500",
            "DATE_STREAM_WATCH_CONCURRENCY": "1",
            "DATE_STREAM_WATCH_TICKERS": MOCK_TICKER,
            "DATE_STREAM_WATCH_COOLDOWN_MINUTES": "1",
            "DATE_STREAM_AUTO_CAPTURE_ENABLED": "true" if with_stt else "false",
            "DATE_STREAM_AUDIO_WAIT_SECONDS": "20",
            "WEBCAST_AUDIO_WARMUP_SECONDS": "1",
            "WEBCAST_CONTROL_TIMEOUT_SECONDS": "20",
        }
    )
    if with_stt:
        os.environ.update(
            {
                "STT_MODEL_NAME": "tiny",
                "STT_MAX_CHUNKS": "1",
                "SEND_TO_AI_ENGINE": "true",
                "SEND_TO_BACKEND": "true",
                "AI_ENGINE_URL": f"http://127.0.0.1:{port}",
                "BACKEND_URL": f"http://127.0.0.1:{port}",
                "INTERNAL_SECRET": "mock-e2e-secret",
                "TRANSCRIPT_ARCHIVE_ENABLED": "true",
                "WEBCAST_HOLD_SECONDS": "20",
            }
        )

    try:
        print(
            f"[MockE2E] seeded {MOCK_TICKER} call_id={call_id} url={url} "
            f"scheduled_at={scheduled_at.isoformat(timespec='seconds')}",
            flush=True,
        )
        orchestrator = EarningsOrchestrator()
        monitor_attempts = 0
        pre_live_error = None
        deadline = time.monotonic() + max(
            30.0,
            scheduled_delay_seconds + 10.0,
        )
        while True:
            monitor_attempts += 1
            await orchestrator.monitor_date_based_streams()
            interim = read_test_result(call_id)
            if interim["stream_probe_status"] == "stream_ready":
                break
            if pre_live_error is None:
                pre_live_error = interim.get("last_stream_probe_error")
            if scheduled_delay_seconds <= 0 or time.monotonic() >= deadline:
                break
            reset_probe_cooldown_for_test(call_id)
            await asyncio.sleep(max(0.1, poll_interval_seconds))
        worker_exit_codes = {}
        if with_stt:
            worker_exit_codes = await orchestrator.worker_manager.wait_for_active_processes(180)
        result = read_test_result(call_id)
        archive_call_id = f"{MOCK_TICKER}-{MOCK_CALL_YEAR}{MOCK_QUARTER}"
        archived_segments = database.get_archived_transcript_segments(archive_call_id)
        post_paths = [path for path, _ in MockWebcastHandler.posts]
        print(
            f"[MockE2E] result={result} worker_exit_codes={worker_exit_codes} "
            f"archived_segments={len(archived_segments)} post_paths={post_paths} "
            f"monitor_attempts={monitor_attempts} pre_live_error={pre_live_error}",
            flush=True,
        )
        if result["stream_probe_status"] != "stream_ready":
            return 1
        if with_stt and (
            not archived_segments
            or "/api/v1/analyze" not in post_paths
            or "/api/v1/internal/transcript-segment" not in post_paths
            or any(code not in {0, None} for code in worker_exit_codes.values())
        ):
            return 1
        if scheduled_delay_seconds > 0 and (
            monitor_attempts < 2
            or not pre_live_error
            or "NOT_LIVE_YET" not in pre_live_error
        ):
            return 1
        print("MOCK_WEBCAST_E2E_PASS", flush=True)
        return 0
    finally:
        server.shutdown()
        server.server_close()
        MockWebcastHandler.set_scheduled_at(None)
        if cleanup:
            cleanup_test_call(call_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local webcast through date-based monitoring.")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--cleanup", action="store_true", help="Remove EWTEST rows after the run.")
    parser.add_argument("--cleanup-only", action="store_true", help="Remove old EWTEST rows without running the browser.")
    parser.add_argument("--with-stt", action="store_true", help="Run tiny Whisper and mock delivery endpoints after audio detection.")
    parser.add_argument(
        "--scheduled-delay-seconds",
        type=float,
        default=0,
        help="Keep the mock event pre-live for this many seconds, then expose registration/playback.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=1,
        help="Delay between date-watcher polls in scheduled mode.",
    )
    args = parser.parse_args()
    if args.cleanup_only:
        cleanup_test_data()
        print("[MockE2E] removed EWTEST test data", flush=True)
        return 0
    return asyncio.run(
        run_e2e(
            args.port,
            cleanup=args.cleanup,
            with_stt=args.with_stt,
            scheduled_delay_seconds=args.scheduled_delay_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
