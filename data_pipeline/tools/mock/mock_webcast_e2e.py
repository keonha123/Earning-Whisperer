from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

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
                       stream_probe_attempts, last_stream_probe_error,
                       capture_session_id
                FROM calls WHERE id = :call_id
            """),
            {"call_id": call_id},
        ).mappings().one()
    return dict(row)


def read_outbox_result(call_id: str) -> dict[str, object]:
    with database.engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT destination, status, COUNT(*) AS count
                FROM transcript_outbox
                WHERE call_id = :call_id
                GROUP BY destination, status
                ORDER BY destination, status
            """),
            {"call_id": call_id},
        ).mappings()
        by_destination: dict[str, dict[str, int]] = {}
        for row in rows:
            destination = str(row["destination"])
            by_destination.setdefault(destination, {})[str(row["status"])] = int(row["count"] or 0)
    return by_destination


def cleanup_test_call(call_id: int) -> None:
    with database.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM transcript_segments WHERE call_id LIKE :call_prefix"),
            {"call_prefix": f"{MOCK_TICKER}-%"},
        )
        conn.execute(
            text("DELETE FROM transcript_outbox WHERE call_id LIKE :call_prefix"),
            {"call_prefix": f"{MOCK_TICKER}-%"},
        )
        conn.execute(text("DELETE FROM calls WHERE id = :call_id"), {"call_id": call_id})
        conn.execute(text("DELETE FROM stocks WHERE ticker = :ticker"), {"ticker": MOCK_TICKER})


def cleanup_test_data() -> None:
    with database.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM transcript_segments WHERE call_id LIKE :call_prefix"),
            {"call_prefix": f"{MOCK_TICKER}-%"},
        )
        conn.execute(
            text("DELETE FROM transcript_outbox WHERE call_id LIKE :call_prefix"),
            {"call_prefix": f"{MOCK_TICKER}-%"},
        )
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
    exercise_retry: bool = False,
    exercise_media_fallback: bool = False,
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
    MockWebcastHandler.set_silent_browser_audio(exercise_media_fallback)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    MockWebcastHandler.set_post_failures(
        {
            "/api/v1/analyze": 1,
            "/api/v1/internal/transcript-segment": 1,
        }
        if with_stt and exercise_retry
        else {}
    )
    approval_file = (
        Path(__file__).resolve().parents[2]
        / ".runtime"
        / "state"
        / "mock-e2e-registration-approval.json"
    )
    approval_file.parent.mkdir(parents=True, exist_ok=True)
    approval_file.write_text(
        json.dumps(
            {
                "approvals": {
                    MOCK_TICKER: {
                        "approved": True,
                        "destination_url": url,
                        "prepared_fields": [
                            "first_name",
                            "last_name",
                            "company",
                            "company_name",
                            "email",
                            "industry_affiliation",
                            "affiliation",
                            "country_select",
                            "other",
                        ],
                        "consent_selected": False,
                    }
                }
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    os.environ.update(
        {
            "WEBCAST_CAPTURE_RUNNER": "container",
            "WEBCAST_ALLOW_REGISTRATION_SUBMISSION": "true",
            "WEBCAST_FIRST_NAME": "Test",
            "WEBCAST_LAST_NAME": "User",
            "WEBCAST_COMPANY": "EWTEST",
            "WEBCAST_EMAIL": "ewtest@example.invalid",
            "WEBCAST_INDUSTRY_AFFILIATION": "Other",
            "WEBCAST_REGISTRATION_APPROVAL_FILE": str(approval_file),
            "WEBCAST_LIFECYCLE": "live",
            # The DB candidate query uses the event timezone date boundary;
            # two days keeps this UTC-based local fixture inside the window.
            "DATE_STREAM_WATCH_DAYS_AHEAD": "2",
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
        # A pre-live probe is deliberately cooled down for one minute by the
        # production retry policy. Give the local E2E enough time to observe
        # that retry rather than bypassing the policy in the fixture.
        retry_grace_seconds = 75.0 if scheduled_delay_seconds > 0 else 0.0
        deadline = time.monotonic() + max(
            30.0,
            scheduled_delay_seconds + retry_grace_seconds,
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
        archive_call_id = str(result.get("capture_session_id") or "")
        if with_stt and exercise_retry:
            with database.engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE transcript_outbox
                        SET next_attempt_at = UTC_TIMESTAMP()
                        WHERE call_id = :call_id AND status = 'failed'
                    """),
                    {"call_id": archive_call_id},
                )
            orchestrator.retry_transcript_outbox()
        archived_segments = database.get_archived_transcript_segments(archive_call_id)
        outbox_result = read_outbox_result(archive_call_id) if with_stt else {}
        post_paths = [path for path, _ in MockWebcastHandler.posts]
        fallback_detected = not exercise_media_fallback
        if exercise_media_fallback:
            artifact_root = Path(__file__).resolve().parents[2] / ".runtime" / "operations" / "probe-artifacts"
            for capture_log in artifact_root.glob("ew-webcast-ewtest-*-capture.log"):
                try:
                    if "AUDIO_DETECTED source=media-stream-fallback" in capture_log.read_text(
                        encoding="utf-8"
                    ):
                        fallback_detected = True
                        break
                except OSError:
                    continue
        print(
            f"[MockE2E] result={result} worker_exit_codes={worker_exit_codes} "
            f"archived_segments={len(archived_segments)} outbox={outbox_result} "
            f"post_paths={post_paths} "
            f"fallback_detected={fallback_detected} "
            f"monitor_attempts={monitor_attempts} pre_live_error={pre_live_error}",
            flush=True,
        )
        if result["stream_probe_status"] != "stream_ready":
            return 1
        terminal_markers = sum(
            1 for segment in archived_segments if bool(segment.get("is_session_end"))
        )
        if with_stt and (
            not archive_call_id
            or not archived_segments
            or terminal_markers < 1
            or "/api/v1/analyze" not in post_paths
            or "/api/v1/internal/transcript-segment" not in post_paths
            or any(
                outbox_result.get(destination, {}).get("sent", 0) < 1
                for destination in ("ai_engine", "backend")
            )
            or any(code not in {0, None} for code in worker_exit_codes.values())
        ):
            return 1
        if exercise_media_fallback and not fallback_detected:
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
        MockWebcastHandler.set_silent_browser_audio(False)
        MockWebcastHandler.set_post_failures({})
        approval_file.unlink(missing_ok=True)
        if cleanup:
            cleanup_test_call(call_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local webcast through date-based monitoring.")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--cleanup", action="store_true", help="Remove EWTEST rows after the run.")
    parser.add_argument("--cleanup-only", action="store_true", help="Remove old EWTEST rows without running the browser.")
    parser.add_argument("--with-stt", action="store_true", help="Run tiny Whisper and mock delivery endpoints after audio detection.")
    parser.add_argument(
        "--exercise-retry",
        action="store_true",
        help="Fail the first downstream delivery, then run the durable outbox retry path.",
    )
    parser.add_argument(
        "--exercise-media-fallback",
        action="store_true",
        help="Make browser playback silent and require the direct MP4 fallback.",
    )
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
            exercise_retry=args.exercise_retry,
            exercise_media_fallback=args.exercise_media_fallback,
            scheduled_delay_seconds=args.scheduled_delay_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
