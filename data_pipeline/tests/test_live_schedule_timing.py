"""Call-time semantics and real candidate SQL against an isolated SQLite DB."""

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest import mock

from sqlalchemy import create_engine, event, text

from data_pipeline.collectors.schedules.enricher import OfficialScheduleEnricher
from data_pipeline.storage import connection, live_calls, schedules, schema


class CallStartSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.enricher = OfficialScheduleEnricher(api_key="test")

    def parse(self, value, day=date(2026, 9, 17)):
        return self.enricher._parse_verified_time(
            value, day, "https://ir.example.test/event", None, "official_ir_event",
        )

    def test_release_then_call_selects_call_time(self):
        value = self.parse(
            "Financial results release September 17, 2026 at 7:00 a.m. ET. "
            "Earnings conference call September 17, 2026 at 5:00 p.m. ET."
        )
        self.assertEqual(value.scheduled_at_utc.isoformat(), "2026-09-17T21:00:00+00:00")

    def test_article_publication_is_not_call_start(self):
        value = self.parse(
            '{"@type":"NewsArticle","datePublished":"2026-09-17T07:00:00-04:00",'
            '"headline":"Earnings results","body":"Earnings conference call '
            'September 17, 2026 at 5:00 PM ET"}'
        )
        self.assertEqual(value.scheduled_at_utc.isoformat(), "2026-09-17T21:00:00+00:00")

    def test_release_only_is_not_verified(self):
        self.assertIsNone(self.parse("Financial results release September 17, 2026 at 7:00 AM ET."))

    def test_publication_timestamp_cannot_borrow_call_headline(self):
        self.assertIsNone(self.parse(
            '{"@type":"NewsArticle","datePublished":"2026-09-17T07:00:00-04:00",'
            '"headline":"Q3 earnings conference call"}'
        ))

    def test_event_json_ignores_published_and_end_dates(self):
        value = self.parse(
            '{"@graph":[{"@type":"NewsArticle","datePublished":"2026-09-17T07:00:00-04:00",'
            '"headline":"Earnings release"},{"@type":"Event","name":"Q3 earnings call",'
            '"startDate":"2026-09-17T17:00:00-04:00","endDate":"2026-09-17T18:00:00-04:00"}]}'
        )
        self.assertEqual(value.scheduled_at_utc.hour, 21)

    def test_conflicting_call_times_remain_unverified(self):
        self.assertIsNone(self.parse(
            "Earnings webcast September 17, 2026 at 4:00 PM ET. "
            "Conference call September 17, 2026 at 5:00 PM ET."
        ))

    def test_conflicting_structured_and_visible_start_remain_unverified(self):
        self.assertIsNone(self.parse(
            '{"@type":"Event","name":"Q3 earnings call","startDate":"2026-09-17T16:00:00-04:00"}\n'
            'Earnings webcast September 17, 2026 at 5:00 PM ET.'
        ))

    def test_conflicting_official_times_report_explicit_invalidation_reason(self):
        self.enricher._page_fetch_succeeded = True
        self.parse(
            "Earnings webcast September 17, 2026 at 4:00 PM ET. "
            "Earnings webcast September 17, 2026 at 5:00 PM ET."
        )
        with mock.patch("data_pipeline.collectors.schedules.enricher.database.record_schedule_enrichment_outcome") as record:
            self.enricher._record_unverified_outcome({"id": 1})
        self.assertEqual(record.call_args.kwargs["failure_kind"], "ambiguous_call_time")

    def test_same_start_in_two_zones_is_one_candidate(self):
        value = self.parse(
            "Earnings webcast September 17, 2026 at 5:00 PM ET. "
            "Earnings webcast September 17, 2026 at 2:00 PM PT."
        )
        self.assertEqual(value.scheduled_at_utc.hour, 21)

    def test_expiry_does_not_replace_call_day(self):
        value = self.parse(
            "Earnings webcast September 17, 2026 at 5:00 PM ET, "
            "replay available until September 18, 2026 at 5:00 PM ET."
        )
        self.assertEqual(value.webcast_date, date(2026, 9, 17))

    def test_event_time_attribute_keeps_semantics(self):
        page_text, _ = self.enricher._extract_page_details(
            '<article><h2>Q3 earnings webcast</h2><time datetime="2026-09-17T17:00:00-04:00"></time></article>',
            "https://ir.example.test/event",
        )
        self.assertEqual(self.parse(page_text).scheduled_at_utc.hour, 21)

    def test_invalid_and_dst_ambiguous_clocks_remain_unverified(self):
        for value, day in (
            ("Earnings webcast September 17, 2026 at 25:99 PM ET", date(2026, 9, 17)),
            ("Earnings webcast March 8, 2026 at 2:30 AM ET", date(2026, 3, 8)),
            ("Earnings webcast November 1, 2026 at 1:30 AM ET", date(2026, 11, 1)),
            ("Earnings webcast at 5:00 PM ET", date(2026, 9, 17)),
        ):
            with self.subTest(value=value):
                self.assertIsNone(self.parse(value, day))

    def test_explicit_dst_offset_can_be_verified(self):
        value = self.parse(
            '{"@type":"Event","name":"Earnings call","startDate":"2026-11-01T01:30:00-04:00"}',
            date(2026, 11, 1),
        )
        self.assertEqual(value.scheduled_at_utc.isoformat(), "2026-11-01T05:30:00+00:00")


class LiveScheduleQueryTest(unittest.TestCase):
    """Execute generated SELECT statements, without rewriting their SQL."""
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        @event.listens_for(self.engine, "before_cursor_execute", retval=True)
        def sqlite_lock_syntax(conn, cursor, statement, parameters, context, executemany):
            return statement.replace(" FOR UPDATE", ""), parameters
        columns = {
            "id": "INTEGER PRIMARY KEY", "ticker": "TEXT", "earning_at": "DATETIME",
            "webcast_date": "DATE", "scheduled_at_utc": "DATETIME", "call_year": "INTEGER",
            "quarter": "TEXT", "status": "TEXT", "video_url": "TEXT", "stream_probe_attempts": "INTEGER",
            "capture_attempts": "INTEGER", "capture_retry_not_before": "DATETIME",
            "stream_probe_retry_not_before": "DATETIME", "stream_probe_retry_reason": "TEXT",
            "time_verification_status": "TEXT", "time_verified_at": "DATETIME",
            "schedule_discovery_checked_at": "DATETIME",
            "schedule_revalidation_status": "TEXT", "schedule_revalidation_reason": "TEXT",
            "schedule_source": "TEXT", "schedule_evidence": "TEXT", "schedule_discovery_fingerprint": "TEXT",
            "event_url": "TEXT", "webcast_url": "TEXT", "last_stream_probe_at": "DATETIME",
            "schedule_enrichment_last_attempt_at": "DATETIME", "schedule_enrichment_retry_not_before": "DATETIME",
            "schedule_enrichment_failure_kind": "TEXT", "schedule_enrichment_last_error": "TEXT",
            "stream_probe_status": "TEXT", "source_timezone": "TEXT",
            "schedule_revision": "INTEGER DEFAULT 0", "schedule_observed_at": "DATETIME",
            "verified_fiscal_year": "INTEGER", "verified_fiscal_quarter": "TEXT",
            "official_event_key": "TEXT", "official_event_identity": "TEXT",
            "schedule_superseded_by": "INTEGER", "schedule_discovery_changed_at": "DATETIME",
            "last_stream_probe_error": "TEXT", "stream_detected_at": "DATETIME",
            "capture_last_error": "TEXT", "capture_session_id": "TEXT",
            "schedule_revalidation_evidence": "TEXT",
        }
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE calls (" + ",".join(f"{k} {v}" for k, v in columns.items()) + ")"))
            conn.execute(text("CREATE TABLE stocks (ticker TEXT PRIMARY KEY, company_name TEXT, ir_url TEXT)"))
            conn.execute(text("CREATE TABLE schedule_change_history (call_id INTEGER, revision INTEGER, reason TEXT, observed_at DATETIME, before_json TEXT, after_json TEXT)"))
            conn.execute(text("CREATE TABLE transcript_segments (call_id TEXT)"))
        self.addCleanup(self.engine.dispose)
        for patch in (mock.patch.object(connection, "engine", self.engine), mock.patch.object(schema, "ensure_schedule_time_schema")):
            patch.start()
            self.addCleanup(patch.stop)
        self.now = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)

    def add_call(self, ticker, **values):
        row = dict(ticker=ticker, earning_at=datetime(2026, 9, 17), status="upcoming",
                   schedule_revalidation_status="clear", time_verification_status="unverified")
        if values.get("scheduled_at_utc"):
            row.update(time_verification_status="verified", time_verified_at=self.now.replace(tzinfo=None))
        row.update(values)
        with self.engine.begin() as conn:
            conn.execute(text("INSERT OR IGNORE INTO stocks VALUES (:ticker, :ticker, 'https://ir.example.test')"), {"ticker": ticker})
            conn.execute(text("INSERT INTO calls (" + ",".join(row) + ") VALUES (" + ",".join(":" + key for key in row) + ")"), row)

    def candidates(self, **kwargs):
        return [row["ticker"] for row in live_calls.get_date_based_stream_candidates(
            reference_time_utc=self.now, **kwargs,
        )]

    def enrichment(self, **kwargs):
        return [row["ticker"] for row in schedules.get_calls_missing_verified_time(
            reference_time_utc=self.now, **kwargs,
        )]

    def test_midnight_keeps_previous_day_exact_call_but_not_stale_date_only(self):
        self.now = datetime(2026, 9, 18, 4, 5, tzinfo=timezone.utc)
        self.add_call("EXACT", scheduled_at_utc=datetime(2026, 9, 18, 3, 30))
        self.add_call("STALE")
        self.assertEqual(self.candidates(), ["EXACT"])

    def test_utc_midnight_does_not_change_new_york_watch_day(self):
        self.now = datetime(2026, 9, 18, 0, 5, tzinfo=timezone.utc)
        self.add_call("TODAY")
        self.assertEqual(self.candidates(), ["TODAY"])
        self.assertEqual(self.enrichment(), ["TODAY"])

    def test_dst_fall_back_both_utc_hours_keep_same_event(self):
        self.add_call("FOLD", earning_at=datetime(2026, 11, 1), scheduled_at_utc=datetime(2026, 11, 1, 5))
        for hour in (5, 6):
            self.now = datetime(2026, 11, 1, hour, 30, tzinfo=timezone.utc)
            self.assertEqual(self.candidates(), ["FOLD"])

    def test_allowlist_is_applied_before_limit(self):
        for index in range(10):
            self.add_call(f"A{index:02}")
        self.add_call("ZZZ")
        self.assertNotIn("ZZZ", self.candidates(limit=10))
        self.assertEqual(self.candidates(limit=10, tickers=[" zzz "]), ["ZZZ"])
        self.assertEqual(self.candidates(tickers=[]), [])
        self.assertEqual(self.candidates(tickers=["ZZZ') OR 1=1 --"]), [])

    def test_overdue_date_only_call_precedes_recently_checked_exact_call(self):
        self.add_call("EXACT", scheduled_at_utc=self.now.replace(tzinfo=None),
                      last_stream_probe_at=(self.now - timedelta(minutes=11)).replace(tzinfo=None))
        self.add_call("DATE", last_stream_probe_at=(self.now - timedelta(minutes=40)).replace(tzinfo=None))
        self.assertEqual(self.candidates(limit=1), ["DATE"])

    def test_due_today_has_priority_over_unseen_future_date(self):
        self.add_call("TODAY", last_stream_probe_at=(self.now - timedelta(minutes=2)).replace(tzinfo=None))
        self.add_call("FUTURE", earning_at=datetime(2026, 9, 18))
        self.assertEqual(self.candidates(days_ahead=2, cooldown_minutes=1, limit=1), ["TODAY"])

    def test_retry_and_quarantine_constraints_survive_aging(self):
        self.add_call("BLOCKED", stream_probe_retry_not_before=(self.now + timedelta(minutes=10)).replace(tzinfo=None))
        self.add_call("QUARANTINED", schedule_revalidation_status="required")
        self.add_call("NORMAL")
        self.assertEqual(self.candidates(), ["NORMAL"])

    def test_today_verified_time_rechecks_before_old_24_hour_ttl(self):
        common = dict(time_verification_status="verified", time_verified_at=(self.now - timedelta(minutes=45)).replace(tzinfo=None))
        self.add_call("TODAY", **common)
        self.add_call("FAR", earning_at=datetime(2026, 9, 24), **common)
        self.add_call("FRESH", time_verification_status="verified", time_verified_at=(self.now - timedelta(minutes=5)).replace(tzinfo=None))
        self.assertEqual(self.enrichment(), ["TODAY"])

    def test_midnight_does_not_prevent_revalidation_of_active_exact_window(self):
        self.now = datetime(2026, 9, 18, 4, 5, tzinfo=timezone.utc)
        self.add_call("EXACT", scheduled_at_utc=datetime(2026, 9, 18, 3, 30),
                      time_verification_status="verified", time_verified_at=datetime(2026, 9, 18, 3))
        self.assertEqual(self.enrichment(), ["EXACT"])

    def test_enrichment_rotates_equal_day_failures_before_ticker_order(self):
        self.add_call("AAAA", schedule_enrichment_last_attempt_at=(self.now - timedelta(hours=1)).replace(tzinfo=None))
        self.add_call("ZZZZ")
        self.assertEqual(self.enrichment(limit=1), ["ZZZZ"])

    def test_explicit_conflict_resumes_date_only_watch_without_clearing_route(self):
        self.add_call("CONFLICT", scheduled_at_utc=datetime(2026, 9, 17, 7),
                      time_verification_status="verified", event_url="https://ir.example.test/current")
        self.assertEqual(self.candidates(), [])
        with self.engine.connect() as conn:
            call_id = conn.execute(text("SELECT id FROM calls")).scalar_one()
        schedules.record_schedule_enrichment_outcome(
            call_id, failure_kind="ambiguous_call_time", error="conflicting times", retry_minutes=30,
        )
        self.assertEqual(self.candidates(), ["CONFLICT"])
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM calls")).mappings().one()
        self.assertEqual(row["time_verification_status"], "unverified")
        self.assertEqual(row["event_url"], "https://ir.example.test/current")

    def test_transient_failure_and_active_probe_do_not_erase_verified_start(self):
        for index, (kind, probe_status) in enumerate((
            ("issuer_http_timeout", "pending"), ("ambiguous_call_time", "probing"),
        )):
            self.add_call(f"KEEP{index}", scheduled_at_utc=datetime(2026, 9, 17, 16),
                          time_verification_status="verified", stream_probe_status=probe_status)
            with self.engine.connect() as conn:
                call_id = conn.execute(text("SELECT id FROM calls WHERE ticker=:ticker"), {"ticker": f"KEEP{index}"}).scalar_one()
            schedules.record_schedule_enrichment_outcome(call_id, failure_kind=kind, error="test", retry_minutes=30)
            with self.engine.connect() as conn:
                self.assertEqual(conn.execute(text("SELECT time_verification_status FROM calls WHERE id=:id"), {"id": call_id}).scalar_one(), "verified")


if __name__ == "__main__":
    unittest.main()
