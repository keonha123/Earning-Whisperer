"""Exercise real candidate SQL when exact start evidence is missing or stale."""

from datetime import datetime, timedelta
from unittest import mock

from sqlalchemy import text

from data_pipeline.application.settings import probe_window
from data_pipeline.storage import live_calls
from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.tests import test_live_schedule_timing as _fixture


class ScheduleWatchFreshnessTest(_fixture.LiveScheduleQueryTest):
    # Reuse the isolated SQL fixture, without collecting its existing tests twice.
    def test_stale_exact_time_does_not_hide_current_date(self):
        self.add_call("STALE", scheduled_at_utc=datetime(2026, 9, 17, 7),
                      time_verified_at=(self.now - timedelta(hours=3)).replace(tzinfo=None))
        rows = live_calls.get_date_based_stream_candidates(reference_time_utc=self.now)
        self.assertEqual([r["ticker"] for r in rows], ["STALE"])
        self.assertTrue(rows[0]["schedule_time_stale"])
        self.assertEqual(STTWorkerManager._target_event_time(rows[0]), "")
        now = self.now
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)
        with mock.patch("data_pipeline.application.settings.datetime", FixedDatetime):
            self.assertEqual(probe_window(rows[0], 1), ("date_only", 1))
        with self.engine.connect() as connection:
            # Falling back does not destroy the previous observation.
            stored = connection.execute(text("SELECT scheduled_at_utc FROM calls")).scalar_one()
        self.assertIsNotNone(stored)

    def test_recent_exact_time_still_limits_probe_window(self):
        self.add_call("FRESH", scheduled_at_utc=datetime(2026, 9, 17, 21))
        self.assertEqual(self.candidates(), [])

    def test_unverified_nonnull_time_does_not_suppress_date_watch(self):
        self.add_call("UNVERIFIED", scheduled_at_utc=datetime(2026, 9, 17, 7),
                      time_verification_status="unverified")
        self.assertEqual(self.candidates(), ["UNVERIFIED"])

    def test_missing_verification_timestamp_does_not_suppress_date_watch(self):
        self.add_call("LEGACY", scheduled_at_utc=datetime(2026, 9, 17, 7), time_verified_at=None)
        self.assertEqual(self.candidates(), ["LEGACY"])

    def test_superseded_duplicate_is_not_dispatched(self):
        self.add_call("DUP", schedule_superseded_by=99)
        self.add_call("CURRENT")
        self.assertEqual(self.candidates(), ["CURRENT"])


# unittest inherits test_* methods. Only this module's scenarios should run here.
for _name in dir(_fixture.LiveScheduleQueryTest):
    if _name.startswith("test_") and _name not in ScheduleWatchFreshnessTest.__dict__:
        setattr(ScheduleWatchFreshnessTest, _name, None)
