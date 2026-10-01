"""Execute probe release + browser clock persistence as one real SQL transaction."""
from datetime import datetime, timedelta, timezone
import os
import re
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from sqlalchemy import event, text

from data_pipeline.storage import live_calls, policies, schedules, schema
from data_pipeline.tests.test_schedule_revision_storage import SQLiteScheduleEngine


class BrowserScheduleStorageTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2035, 9, 22, 12)
        self.engine = SQLiteScheduleEngine()
        self.addCleanup(self.engine.raw.dispose)

        @event.listens_for(self.engine.raw, "before_cursor_execute", retval=True)
        def sqlite_dates(conn, cursor, statement, parameters, context, executemany):
            if self.engine.raw.dialect.name != 'sqlite':
                return statement, parameters
            statement = re.sub(
                r"DATE_(ADD|SUB)\(\s*UTC_TIMESTAMP\(\),\s*INTERVAL\s+(\d+)\s+MINUTE\s*\)",
                lambda match: "datetime('" + str(self.now) + "', '"
                + ("+" if match[1] == "ADD" else "-") + match[2] + " minutes')",
                statement, flags=re.I,
            ).replace("UTC_TIMESTAMP()", "'" + str(self.now) + "'")
            return statement, parameters

        fixed = self.now

        class ClockMeta(type):
            def __instancecheck__(cls, value):
                return isinstance(value, datetime)

        class Clock(datetime, metaclass=ClockMeta):
            @classmethod
            def now(cls, tz=None):
                return fixed.replace(tzinfo=timezone.utc).astimezone(tz) if tz else fixed

            @classmethod
            def fromisoformat(cls, value):
                return datetime.fromisoformat(value)

        self.clock = Clock
        for target, name, value in (
            (live_calls.connection, "engine", self.engine),
            (schema, "ensure_schedule_time_schema", lambda: None),
            (live_calls, "datetime", Clock),
            (policies, "datetime", Clock),
        ):
            context = patch.object(target, name, value)
            context.start()
            self.addCleanup(context.stop)
        environment = patch.dict(os.environ, {"PIPELINE_WORKER_ID": "browser-clock-test",
                                             "DATE_STREAM_EARLY_ENTRY_MINUTES": "5"})
        environment.start()
        self.addCleanup(environment.stop)
        self.owner = live_calls._pipeline_worker_id()
        with self.engine.raw.begin() as conn:
            conn.execute(text("""
                INSERT INTO calls (id, ticker, earning_at, webcast_date,
                    schedule_revision, stream_probe_status, stream_probe_lease_owner,
                    stream_probe_lease_until, last_stream_probe_at, stream_probe_attempts,
                    event_url, webcast_url)
                VALUES (1, 'TEST', :day, :day, 7, 'probing', :owner,
                    :lease, :probe_at, 1, 'https://issuer.test/event', 'https://provider.test/123')
            """), {"day": self.now.date(), "owner": self.owner, "lease": self.now + timedelta(minutes=10),
                   "probe_at": self.now - timedelta(minutes=1)})

    def row(self):
        with self.engine.raw.connect() as conn:
            return dict(conn.execute(text("SELECT * FROM calls WHERE id=1")).mappings().one())

    def update(self, **values):
        with self.engine.raw.begin() as conn:
            conn.execute(text("UPDATE calls SET " + ", ".join(f"{key}=:{key}" for key in values)
                              + " WHERE id=1"), values)

    def history_count(self):
        with self.engine.raw.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM schedule_change_history")).scalar_one()

    def evidence(self, **extra):
        return {"webcast_date": self.now.date(),
                "scheduled_at_utc": (self.now + timedelta(hours=2)).isoformat(),
                "source_timezone": "America/New_York",
                "schedule_source": "official_browser_provider",
                "schedule_evidence": "Matched Q4 earnings call, September 22, 10 a.m. ET",
                "observed_at": self.now.isoformat(), **extra}

    def finish(self, *, evidence=None, revision=7, ready=False, **extra):
        return live_calls.record_stream_probe(
            1, stream_ready=ready, error=extra.pop("error", "NOT_LIVE_YET waiting"),
            watch_state="event_window", expected_date=self.now.date(),
            expected_schedule_revision=revision,
            schedule_observation=self.evidence() if evidence is None else evidence, **extra,
        )

    def seed_verified(self, start=None):
        self.update(scheduled_at_utc=start or self.now + timedelta(hours=2),
                    source_timezone="America/New_York", time_verification_status="verified", time_verified_at=self.now)

    def test_future_clock_release_and_wait_are_committed_together(self):
        result = self.finish(error="NOT_LIVE_YET scheduled event time is in the future: 2035-09-22T19:00:00Z")
        row = self.row()
        self.assertTrue(result["accepted"])
        self.assertTrue(result["schedule_applied"])
        self.assertTrue(result["schedule_changed"])
        self.assertFalse(result["capture_handoff_valid"])
        self.assertEqual(row["scheduled_at_utc"], "2035-09-22 14:00:00")
        self.assertEqual(row["stream_probe_retry_not_before"], "2035-09-22 13:55:00")
        self.assertEqual(row["stream_probe_retry_reason"], "scheduled_start_wait")
        self.assertEqual(row["schedule_revision"], 8)
        self.assertIsNone(row["stream_probe_lease_owner"])
        self.assertEqual(self.history_count(), 1)

    def test_moved_clock_replaces_previous_later_and_earlier_waits(self):
        for hours in (1, 3):
            with self.subTest(hours=hours):
                self.setUpCase()
                self.seed_verified()
                self.update(stream_probe_retry_not_before=self.now + timedelta(hours=2),
                            stream_probe_retry_reason="scheduled_start_wait")
                start = self.now + timedelta(hours=hours)
                result = self.finish(evidence=self.evidence(scheduled_at_utc=start.isoformat()))
                self.assertEqual(self.row()["stream_probe_retry_not_before"],
                                 str(start - timedelta(minutes=5)))
                self.assertEqual(result["schedule_context"]["schedule_revision"], 8)

    def setUpCase(self):
        self.update(status="upcoming", stream_probe_status="probing", schedule_revision=7,
                    schedule_observed_at=None, stream_probe_lease_owner=self.owner,
                    stream_probe_lease_until=self.now + timedelta(minutes=10),
                    last_stream_probe_at=self.now - timedelta(minutes=1))

    def test_clock_moved_to_now_clears_old_wait_and_invalidates_handoff(self):
        self.seed_verified()
        result = self.finish(ready=True, evidence=self.evidence(scheduled_at_utc=self.now.isoformat()))
        self.assertTrue(result["schedule_changed"])
        self.assertFalse(result["capture_handoff_valid"])
        self.assertIsNone(self.row()["stream_probe_retry_not_before"])
        self.assertEqual(self.row()["stream_probe_status"], "pending")

    def test_unchanged_clock_allows_ready_handoff_and_refreshes_freshness(self):
        self.seed_verified(self.now)
        result = self.finish(ready=True, evidence=self.evidence(scheduled_at_utc=self.now.isoformat()))
        self.assertTrue(result["capture_handoff_valid"])
        self.assertFalse(result["schedule_changed"])
        self.assertEqual(self.row()["stream_probe_status"], "stream_ready")
        self.assertEqual(self.row()["schedule_revision"], 7)
        self.assertEqual(self.row()["time_verified_at"], str(self.now))

    def test_unchanged_future_clock_still_prevents_early_capture(self):
        self.seed_verified()
        result = self.finish(ready=True)
        self.assertFalse(result["capture_handoff_valid"])
        self.assertFalse(result["schedule_changed"])
        self.assertEqual(self.row()["stream_probe_status"], "pending")

    def test_due_database_clock_overrides_old_future_error_marker(self):
        self.seed_verified(self.now)
        result = self.finish(evidence=self.evidence(scheduled_at_utc=self.now.isoformat()),
                             error="NOT_LIVE_YET scheduled event time is in the future: 2035-09-22T19:00:00Z")
        self.assertNotEqual(result["reason"], "scheduled_start_wait")
        self.assertLessEqual(schedules._utc_naive(self.row()["stream_probe_retry_not_before"]),
                             self.now + timedelta(minutes=1))

    def test_stale_revision_owner_expired_lease_and_active_capture_are_untouched(self):
        original = self.row()
        for mismatch in ({"schedule_revision": 8}, {"stream_probe_lease_owner": "another-worker"},
                         {"stream_probe_lease_until": self.now - timedelta(seconds=1)},
                         {"status": "running"}, {"status": "completed"},
                         {"schedule_superseded_by": 2}, {"stream_probe_status": "pending"}):
            with self.subTest(mismatch=mismatch):
                self.update(**original)
                self.update(**mismatch)
                before = self.row()
                self.assertFalse(self.finish()["accepted"])
                self.assertEqual(self.row(), before)
        self.assertEqual(self.history_count(), 0)

    def test_missing_revision_cannot_release_probe(self):
        before = self.row()
        self.assertFalse(self.finish(revision=None)["accepted"])
        self.assertEqual(self.row(), before)

    def test_same_revision_newer_observation_blocks_late_probe(self):
        self.update(schedule_observed_at=self.now + timedelta(seconds=1))
        before = self.row()
        self.assertFalse(self.finish()["accepted"])
        self.assertEqual(self.row(), before)

    def test_old_attempt_from_same_worker_cannot_release_new_probe(self):
        self.update(last_stream_probe_at=self.now + timedelta(seconds=1))
        before = self.row()
        self.assertFalse(self.finish()["accepted"])
        self.assertEqual(self.row(), before)

    def test_bad_clock_evidence_never_persists_or_authorizes_capture(self):
        original = self.row()
        for bad in ({"observed_at": None}, {"observed_at": "invalid"},
                    {"observed_at": 1234}, {"source_timezone": "bogus"},
                    {"observed_at": (self.now + timedelta(minutes=3)).isoformat()},
                    {"scheduled_at_utc": "2035-09-23T14:00:00"},
                    {"webcast_date": "2035-09-23"}):
            with self.subTest(bad=bad):
                self.update(**original)
                result = self.finish(ready=True, evidence=self.evidence(**bad))
                self.assertTrue(result["accepted"])
                self.assertFalse(result["schedule_applied"])
                self.assertFalse(result["capture_handoff_valid"])
                self.assertIsNone(self.row()["scheduled_at_utc"])
        self.assertEqual(self.history_count(), 0)

    def test_official_refresh_still_refuses_active_probe_but_browser_commit_succeeds(self):
        self.assertIsNone(schedules.update_verified_schedule_time(1, self.evidence(expected_revision=7)))
        self.assertTrue(self.finish()["schedule_applied"])

    def test_no_new_observation_respects_current_db_clock_and_owner(self):
        self.seed_verified()
        result = live_calls.record_stream_probe(
            1, stream_ready=True, expected_date=self.now.date(), expected_schedule_revision=7,
        )
        self.assertTrue(result["accepted"])
        self.assertFalse(result["schedule_applied"])
        self.assertFalse(result["capture_handoff_valid"])
        self.assertEqual(self.row()["stream_probe_retry_not_before"], "2035-09-22 13:55:00")
        self.setUpCase()
        self.seed_verified(self.now)
        result = live_calls.record_stream_probe(
            1, stream_ready=True, expected_date=self.now.date(), expected_schedule_revision=7,
        )
        self.assertTrue(result["capture_handoff_valid"])
        self.assertEqual(self.row()["stream_probe_status"], "stream_ready")

    def test_no_observation_due_clock_overrides_stale_wait_error(self):
        self.seed_verified(self.now)
        result = live_calls.record_stream_probe(
            1, stream_ready=False, expected_date=self.now.date(), expected_schedule_revision=7,
            error="NOT_LIVE_YET scheduled event time is in the future: 2035-09-22T19:00:00Z",
        )
        self.assertEqual(result["reason"], "transient_error")
        self.assertEqual(self.row()["stream_probe_retry_not_before"], "2035-09-22 12:01:00")

    def test_actual_browser_observation_with_edt_reaches_database(self):
        from data_pipeline.collectors.schedules import browser_observation
        from data_pipeline.collectors.streams.browser import navigation
        evidence = "TEST Q4 2035 earnings conference call September 22, 2035 at 10:30 AM EDT"
        proof = dict(verified=True, call_ticker="TEST", target_date=self.now.date().isoformat(),
                     source_url="https://issuer.test/event", target_url="https://provider.test/123",
                     observed_at=self.now.replace(tzinfo=timezone.utc).isoformat())
        agent = SimpleNamespace(lifecycle="live", ticker="TEST", target_date=self.now.date(),
                                live_target_proof=proof)
        call = {**self.row(), "ir_url": "https://issuer.test/events"}
        with patch.object(browser_observation, "datetime", self.clock), \
                patch.object(navigation, "datetime", self.clock), \
                patch("data_pipeline.live_telemetry.emit_live_event"):
            observed = browser_observation.observe_browser_time(agent, evidence)
            values = browser_observation.validated_browser_values(call, observed)
        self.assertIsNotNone(values)
        self.assertEqual(values["source_timezone"], "EDT")
        result = self.finish(evidence=values)
        self.assertTrue(result["schedule_applied"])
        self.assertEqual(self.row()["scheduled_at_utc"], "2035-09-22 14:30:00")
        self.assertEqual(self.row()["stream_probe_retry_not_before"], "2035-09-22 14:25:00")

    def test_iso_offset_zone_from_semantic_browser_clock_is_supported(self):
        result = self.finish(evidence=self.evidence(source_timezone="UTC-04:00"))
        self.assertTrue(result["schedule_applied"])
        self.assertEqual(self.row()["source_timezone"], "UTC-04:00")

    def test_exception_after_probe_release_rolls_back_entire_transaction(self):
        before = self.row()
        with patch.object(schedules, "_append_history", side_effect=RuntimeError("storage fault")):
            with self.assertRaisesRegex(RuntimeError, "storage fault"):
                self.finish()
        self.assertEqual(self.row(), before)
        self.assertEqual(self.history_count(), 0)


if __name__ == "__main__":
    unittest.main()
