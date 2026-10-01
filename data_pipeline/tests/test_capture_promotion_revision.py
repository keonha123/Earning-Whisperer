"""Execute real probe-to-capture SQL; optionally repeat against isolated MySQL.

EW_PROMOTION_TEST_DB_URL must name an empty database called ew_promotion_test.
Without it, SQLite changes only MySQL date/null-safe comparison syntax. In
particular, promotion predicates and UPDATE assignment order are never mocked.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import tempfile
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from data_pipeline.application.live_watch import LiveWatchService
from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.storage import live_calls, schema


class _HeldBrowser:
    """A process that exits when the real manager writes its abort signal."""

    def __init__(self, abort_file):
        self.abort_file = Path(abort_file)
        self.returncode = None
        self.wait_count = 0

    async def wait(self):
        self.wait_count += 1
        if not self.abort_file.exists():
            raise AssertionError("Browser was reaped without an abort signal")
        self.returncode = 0
        return self.returncode


class _AudibleWorker(STTWorkerManager):
    """Fake browser/STT boundaries, with real held-process ownership cleanup."""

    def __init__(self, directory, now, read_row, mutate_after_probe=None):
        super().__init__()
        self.directory = Path(directory)
        self.now = now
        self.read_row = read_row
        self.mutate_after_probe = mutate_after_probe
        self.phases = []
        self.launches = []
        self.held = None

    def build_isolated_capture_environment(self, call, capture_env=None):
        return dict(capture_env or {})

    async def discover_date_based_call(self, call):
        return {
            "target_identity_verified": True,
            "discovered_url": call["webcast_url"],
            "identity_proof": {
                "verified": True,
                "call_ticker": call["ticker"],
                "target_date": str(call["webcast_date"])[:10],
                "source_url": call["ir_url"],
                "target_url": call["webcast_url"],
                "observed_at": self.now.replace(tzinfo=timezone.utc).isoformat(),
            },
        }

    async def probe_date_based_call(self, call, *, capture_env=None):
        output_task = asyncio.get_running_loop().create_future()
        output_task.set_result(None)
        abort_file = str(self.directory / "browser.abort")
        self.held = SimpleNamespace(
            process=_HeldBrowser(abort_file),
            output_task=output_task,
            runtime_environment=dict(capture_env or {}),
            promote_file=str(self.directory / "browser.promote"),
            abort_file=abort_file,
        )
        self._promotable_probes[self._build_call_id(call)] = self.held
        self.phases.append("audible_probe")
        if self.mutate_after_probe is not None:
            self.mutate_after_probe()
        return True, None

    async def launch_date_based_audio_capture(self, call, *, capture_env=None):
        # This snapshot proves real mark_call_running committed before launch.
        self.launches.append((dict(call), dict(capture_env or {}), self.read_row()))
        self.phases.append("stt_launch")
        held = self._promotable_probes.pop(self._build_call_id(call))
        self._active_processes[self._build_call_id(call)] = held.process


class CapturePromotionRevisionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2035, 9, 22, 12)
        self.directory = tempfile.TemporaryDirectory(prefix="ew-promotion-test-")
        self.addCleanup(self.directory.cleanup)
        configured_url = os.environ.get("EW_PROMOTION_TEST_DB_URL")
        if configured_url:
            url = make_url(configured_url)
            if url.get_backend_name() != "mysql" or url.database != "ew_promotion_test":
                raise ValueError(
                    "EW_PROMOTION_TEST_DB_URL must use MySQL database ew_promotion_test"
                )
        else:
            url = "sqlite:///" + str(Path(self.directory.name) / "promotion.sqlite")
        self.engine = create_engine(url)
        self.addCleanup(self.engine.dispose)
        self.executed_sql = []

        @event.listens_for(self.engine, "before_cursor_execute", retval=True)
        def adapt_sqlite_syntax(conn, cursor, statement, parameters, context, executemany):
            self.executed_sql.append(statement)
            if self.engine.dialect.name == "sqlite":
                statement = re.sub(
                    r"DATE_(ADD|SUB)\(\s*UTC_TIMESTAMP\(\),\s*INTERVAL\s+(\d+)\s+MINUTE\s*\)",
                    lambda match: "datetime('" + str(self.now) + "', '"
                    + ("+" if match[1] == "ADD" else "-") + match[2] + " minutes')",
                    statement,
                    flags=re.IGNORECASE,
                )
                statement = statement.replace("UTC_TIMESTAMP()", "'" + str(self.now) + "'")
                statement = statement.replace("<=>", " IS ")
                statement = statement.replace(" FOR UPDATE", "")
            return statement, parameters

        # Deliberately fail if the isolated database already contains calls;
        # do not drop somebody else's table or migrate any production schema.
        columns = ", ".join(
            name + " " + definition for name, definition in schema.SCHEDULE_TIME_COLUMNS.items()
        )
        with self.engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE calls (id INTEGER PRIMARY KEY, ticker VARCHAR(20), "
                "earning_at DATETIME, call_year INTEGER, quarter VARCHAR(8), "
                "status VARCHAR(32) DEFAULT 'upcoming', video_url TEXT, " + columns + ")"
            ))
        self.addCleanup(self.drop_test_table)
        engine_patch = patch.object(live_calls.connection, "engine", self.engine)
        engine_patch.start()
        self.addCleanup(engine_patch.stop)
        schema_patch = patch.object(schema, "ensure_schedule_time_schema")
        schema_patch.start()
        self.addCleanup(schema_patch.stop)
        environment = patch.dict(os.environ, {
            "DATE_STREAM_DISCOVERY_ENABLED": "true",
            "DATE_STREAM_AUTO_CAPTURE_ENABLED": "true",
            "PIPELINE_WORKER_ID": "promotion-regression-worker",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.call = {
            "id": 1,
            "ticker": "TEST",
            "earning_at": self.now,
            "webcast_date": self.now.date(),
            "scheduled_at_utc": self.now + timedelta(minutes=1),
            "call_year": 2035,
            "quarter": "Q3",
            "schedule_revision": 7,
            "schedule_discovery_fingerprint": "a" * 64,
            "event_url": "https://issuer.invalid/events/q3",
            "webcast_url": "https://webcast.invalid/q3",
        }
        with self.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO calls (" + ", ".join(self.call) + ") VALUES ("
                + ", ".join(":" + name for name in self.call) + ")"
            ), self.call)
        self.call["ir_url"] = "https://issuer.invalid/events"

    def drop_test_table(self):
        with self.engine.begin() as conn:
            conn.execute(text("DROP TABLE calls"))

    def row(self):
        with self.engine.connect() as conn:
            return dict(conn.execute(text("SELECT * FROM calls WHERE id=1")).mappings().one())

    def update(self, **values):
        with self.engine.begin() as conn:
            conn.execute(text(
                "UPDATE calls SET " + ", ".join(name + "=:" + name for name in values)
                + " WHERE id=1"
            ), values)

    def identity(self):
        return {
            "expected_event_date": self.call["webcast_date"],
            "expected_discovery_fingerprint": self.call["schedule_discovery_fingerprint"],
            "expected_schedule_revision": self.call["schedule_revision"],
        }

    def assert_unclaimed(self, before):
        self.assertEqual(self.row(), before)

    def test_current_revision_claims_capture_and_preserves_original_status(self):
        for status in ("upcoming", "live"):
            with self.subTest(status=status):
                self.update(status=status, capture_attempts=0, capture_lease_until=None,
                            capture_previous_status=None)
                self.assertTrue(live_calls.mark_call_running(
                    1, capture_session_id="regression-session", **self.identity()
                ))
                row = self.row()
                self.assertEqual(row["status"], "running")
                self.assertEqual(row["capture_previous_status"], status)
                self.assertEqual(row["capture_attempts"], 1)
                self.assertEqual(row["capture_session_id"], "regression-session")
                for field in ("capture_lease_owner", "capture_lease_until",
                              "capture_started_at", "capture_heartbeat_at"):
                    self.assertIsNotNone(row[field], field)

    def test_stale_revision_rejects_even_when_date_url_and_fingerprint_match(self):
        self.update(schedule_revision=8)
        before = self.row()
        self.assertFalse(live_calls.mark_call_running(
            1, capture_session_id="stale-session", **self.identity()
        ))
        self.assert_unclaimed(before)

    def test_sql_preserves_previous_status_before_mysql_assignment_changes_status(self):
        # SQLite evaluates SET expressions together; MySQL evaluates left to
        # right. Retain a SQL-order regression check for the SQLite-only run.
        self.assertTrue(live_calls.mark_call_running(1))
        promotion_sql = next(statement for statement in reversed(self.executed_sql)
                             if re.search(r"UPDATE\s+calls\s+SET", statement, re.I))
        previous = re.search(r"\bcapture_previous_status\s*=\s*status\b", promotion_sql)
        running = re.search(r"\bstatus\s*=\s*'running'", promotion_sql)
        self.assertIsNotNone(previous)
        self.assertIsNotNone(running)
        self.assertLess(previous.start(), running.start())

    def test_revision_guard_also_applies_without_event_date(self):
        before = self.row()
        self.assertFalse(live_calls.mark_call_running(1, expected_schedule_revision=6))
        self.assert_unclaimed(before)
        self.assertTrue(live_calls.mark_call_running(1, expected_schedule_revision=7))

    def test_zero_revision_is_compared_instead_of_treated_as_missing(self):
        before = self.row()
        self.assertFalse(live_calls.mark_call_running(1, expected_schedule_revision=0))
        self.assert_unclaimed(before)
        self.update(schedule_revision=0)
        self.assertTrue(live_calls.mark_call_running(1, expected_schedule_revision=0))

    def test_legacy_callers_can_omit_revision_or_explicitly_pass_none(self):
        for kwargs in ({}, {"expected_schedule_revision": None}):
            with self.subTest(kwargs=kwargs):
                self.update(status="upcoming", capture_lease_until=None, capture_attempts=0)
                self.assertTrue(live_calls.mark_call_running(1, **kwargs))
                self.assertEqual(self.row()["capture_attempts"], 1)

    def test_superseded_call_cannot_capture_with_current_revision_or_legacy_api(self):
        self.update(schedule_superseded_by=2)
        before = self.row()
        for kwargs in ({}, self.identity()):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(live_calls.mark_call_running(1, **kwargs))
                self.assert_unclaimed(before)

    def test_date_and_null_safe_fingerprint_checks_remain_effective(self):
        for mismatch in (
            {"expected_event_date": self.now.date() + timedelta(days=1)},
            {"expected_discovery_fingerprint": "b" * 64},
            {"expected_discovery_fingerprint": None},
        ):
            with self.subTest(mismatch=mismatch):
                before = self.row()
                self.assertFalse(live_calls.mark_call_running(1, **{**self.identity(), **mismatch}))
                self.assert_unclaimed(before)
        self.update(schedule_discovery_fingerprint=None)
        self.assertTrue(live_calls.mark_call_running(
            1, **{**self.identity(), "expected_discovery_fingerprint": None}
        ))

    def test_existing_lease_and_ineligible_status_still_prevent_claims(self):
        for values in (
            {"capture_lease_until": datetime(2099, 1, 1)},
            {"status": "running"},
            {"status": "completed"},
            {"schedule_revalidation_status": "cancelled"},
        ):
            with self.subTest(values=values):
                self.update(status="upcoming", capture_lease_until=None,
                            schedule_revalidation_status="clear")
                self.update(**values)
                before = self.row()
                self.assertFalse(live_calls.mark_call_running(1, **self.identity()))
                self.assert_unclaimed(before)

    def test_competing_promotions_commit_exactly_one_capture_claim(self):
        barrier = Barrier(2)

        def claim(session):
            barrier.wait(timeout=5)
            return session, live_calls.mark_call_running(
                1, capture_session_id=session, **self.identity()
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ["session-one", "session-two"]))
        winners = [session for session, won in results if won]
        self.assertEqual(len(winners), 1)
        row = self.row()
        self.assertEqual(row["capture_session_id"], winners[0])
        self.assertEqual(row["capture_attempts"], 1)
        self.assertEqual(row["capture_previous_status"], "upcoming")

    async def run_audible_probe(self, mutate_after_probe=None):
        worker = _AudibleWorker(self.directory.name, self.now, self.row, mutate_after_probe)
        health = Mock()
        service = LiveWatchService(live_calls, worker, Mock(), health)
        # The test exercises promotion, independent of the wall clock/watch window.
        with patch("data_pipeline.application.live_watch.probe_window",
                   return_value=("event_window", 1)):
            await service._probe_and_launch_date_stream_call(dict(self.call), {
                "cooldown_minutes": 1, "capture_concurrency": 1,
            })
        self.assertEqual(service._capture_reservations, set())
        self.assertEqual(service._preparing_call_ids, set())
        health.database_unavailable.assert_not_called()
        return worker, health

    async def test_audible_probe_calls_real_mark_running_before_fake_stt_launch(self):
        worker, health = await self.run_audible_probe()
        self.assertEqual(worker.phases, ["audible_probe", "stt_launch"])
        self.assertEqual(len(worker.launches), 1)
        call, environment, row_at_launch = worker.launches[0]
        self.assertEqual(row_at_launch["status"], "running")
        self.assertEqual(row_at_launch["capture_previous_status"], "upcoming")
        self.assertEqual(row_at_launch["capture_attempts"], 1)
        self.assertEqual(row_at_launch["capture_session_id"], call["_capture_session_id"])
        self.assertEqual(row_at_launch["capture_session_id"], environment["STT_CAPTURE_SESSION_ID"])
        self.assertEqual(row_at_launch["stream_probe_status"], "stream_ready")
        self.assertIsNone(row_at_launch["stream_probe_lease_owner"])
        self.assertEqual(worker._promotable_probes, {})
        self.assertEqual(worker.held.process.wait_count, 0)
        self.assertTrue(any(call.args[0] == "capture_started"
                            for call in health.record_event.call_args_list))

    async def test_revision_changed_after_audible_probe_rejects_and_reaps_browser(self):
        original = self.row()
        worker, health = await self.run_audible_probe(lambda: self.update(schedule_revision=8))
        self.assertEqual(worker.phases, ["audible_probe"])
        self.assertEqual(worker.launches, [])
        row = self.row()
        self.assertEqual(row["schedule_revision"], 8)
        for field in ("webcast_date", "event_url", "webcast_url", "schedule_discovery_fingerprint"):
            self.assertEqual(row[field], original[field], field)
        self.assertEqual(row["status"], "upcoming")
        self.assertEqual(row["capture_attempts"], 0)
        for field in ("capture_session_id", "capture_lease_owner", "capture_lease_until",
                      "capture_started_at", "capture_heartbeat_at", "capture_previous_status"):
            self.assertIsNone(row[field], field)
        self.assertEqual(worker._promotable_probes, {})
        self.assertEqual(worker.occupied_capture_keys(), set())
        self.assertEqual(worker.held.process.returncode, 0)
        self.assertEqual(worker.held.process.wait_count, 1)
        self.assertTrue(Path(worker.held.abort_file).exists())
        self.assertFalse(Path(worker.held.promote_file).exists())
        skipped = [call for call in health.record_event.call_args_list
                   if call.args[0] == "capture_skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0].kwargs["status"], "schedule_changed_or_claimed")


if __name__ == "__main__":
    unittest.main()
