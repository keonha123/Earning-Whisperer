from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
import inspect
import unittest
from unittest import mock

import requests

from data_pipeline import database
from data_pipeline.storage import connection, schema
from sqlalchemy import text
from data_pipeline.tests.test_schedule_revision_storage import SQLiteScheduleEngine
from data_pipeline.collectors.schedules.nasdaq import NasdaqEarningsCalendar
from data_pipeline.orchestrator import EarningsOrchestrator


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.rowcount = 1

    def mappings(self) -> "_FakeResult":
        return self

    def __iter__(self):
        return iter(self.rows)


class _FakeConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        statement_text = str(statement)
        self.executed.append((statement_text, dict(params or {})))
        if "SELECT id, ticker, earning_at, schedule_last_yahoo_seen_at" in statement_text:
            return _FakeResult(self.rows)
        return _FakeResult()


class _FakeEngine:
    def __init__(self, rows: list[dict]) -> None:
        self.connection = _FakeConnection(rows)

    @contextmanager
    def begin(self):
        yield self.connection


class NasdaqEarningsCalendarTest(unittest.TestCase):
    def test_collects_only_known_tickers_and_keeps_failed_days_explicit(self):
        start = date(2026, 8, 25)
        response = _FakeResponse(
            {
                "data": {
                    "rows": [
                        {"symbol": "BRK.B", "name": "Berkshire", "time": "time-not-supplied"},
                        {"symbol": "OUTSIDE", "name": "Ignored"},
                    ]
                }
            }
        )
        with mock.patch(
            "data_pipeline.collectors.schedules.nasdaq.requests.get",
            side_effect=[response, requests.RequestException("temporary outage")],
        ) as get:
            result = NasdaqEarningsCalendar(timeout_seconds=12).collect(
                start_date=start,
                days_ahead=2,
                tickers=["BRK-B", "MSFT"],
            )

        self.assertEqual(len(result.schedules), 1)
        self.assertEqual(result.schedules[0]["ticker"], "BRK-B")
        self.assertEqual(result.schedules[0]["earning_date"], start)
        self.assertEqual(result.fetched_dates, {start})
        self.assertIn(date(2026, 8, 26), result.failed_dates)
        self.assertEqual(get.call_count, 2)


class ScheduleReconciliationDatabaseTest(unittest.TestCase):
    def _run_reconciliation(self, rows, schedules, fetched_dates):
        fake_engine = _FakeEngine(rows)
        observed_at = datetime(2026, 8, 20, 9, 0)
        with (
            mock.patch.object(schema, "ensure_schedule_time_schema"),
            mock.patch.object(connection, "engine", fake_engine),
        ):
            summary = database.reconcile_near_term_schedule_sources(
                schedules,
                yahoo_observed_at=observed_at,
                nasdaq_fetched_dates=fetched_dates,
                start_date=date(2026, 8, 20),
                days_ahead=14,
                observed_at=datetime(2026, 8, 20, 9, 1),
            )
        return summary, fake_engine.connection.executed

    def test_date_mismatch_preserves_primary_date_and_enables_provisional_watch(self):
        summary, executed = self._run_reconciliation(
            [
                {
                    "id": 1,
                    "ticker": "VEEV",
                    "earning_at": datetime(2026, 9, 2),
                    "schedule_last_yahoo_seen_at": datetime(2026, 8, 19, 9, 0),
                }
            ],
            [{"ticker": "VEEV", "earning_date": date(2026, 8, 26)}],
            {date(2026, 8, 26)},
        )

        self.assertEqual(summary["date_mismatches"], 1)
        mismatch_updates = [
            params
            for statement, params in executed
            if "schedule_revalidation_reason = 'date_mismatch'" in statement
        ]
        self.assertEqual(len(mismatch_updates), 1)
        self.assertNotIn("earning_date", mismatch_updates[0])
        mismatch_sql = next(
            statement
            for statement, _ in executed
            if "schedule_revalidation_reason = 'date_mismatch'" in statement
        )
        self.assertIn("schedule_revalidation_status = 'provisional_watch'", mismatch_sql)
        self.assertNotIn("SET earning_at", mismatch_sql)

    def test_missing_yahoo_row_requires_ir_revalidation_without_nasdaq_failure_guess(self):
        summary, executed = self._run_reconciliation(
            [
                {
                    "id": 2,
                    "ticker": "INTU",
                    "earning_at": datetime(2026, 8, 25),
                    "schedule_last_yahoo_seen_at": datetime(2026, 8, 19, 9, 0),
                }
            ],
            [],
            {date(2026, 8, 25)},
        )

        self.assertEqual(summary["yahoo_missing"], 1)
        revalidation_updates = [
            params
            for statement, params in executed
            if "schedule_revalidation_status = 'provisional_watch'" in statement
            and "COALESCE" in statement
        ]
        self.assertEqual(revalidation_updates[0]["reason"], "yahoo_source_missing")

    def test_unfetched_nasdaq_day_does_not_mark_a_missing_yahoo_row(self):
        summary, executed = self._run_reconciliation(
            [
                {
                    "id": 3,
                    "ticker": "MSFT",
                    "earning_at": datetime(2026, 8, 25),
                    "schedule_last_yahoo_seen_at": datetime(2026, 8, 19, 9, 0),
                }
            ],
            [],
            set(),
        )

        self.assertEqual(summary["yahoo_missing"], 0)
        self.assertFalse(
            any("schedule_revalidation_status = 'required'" in statement for statement, _ in executed)
        )

    def test_second_precision_yahoo_observation_is_not_mistaken_for_a_missing_row(self):
        fake_engine = _FakeEngine(
            [
                {
                    "id": 4,
                    "ticker": "AVGO",
                    "earning_at": datetime(2026, 9, 2),
                    "schedule_last_yahoo_seen_at": datetime(2026, 8, 30, 17, 38, 40),
                    "schedule_revalidation_reason": None,
                }
            ]
        )
        with (
            mock.patch.object(schema, "ensure_schedule_time_schema"),
            mock.patch.object(connection, "engine", fake_engine),
        ):
            summary = database.reconcile_near_term_schedule_sources(
                [{"ticker": "AVGO", "earning_date": date(2026, 9, 2)}],
                yahoo_observed_at=datetime(2026, 8, 30, 17, 38, 40, 900_000),
                nasdaq_fetched_dates={date(2026, 9, 2)},
                start_date=date(2026, 8, 30),
                days_ahead=14,
                observed_at=datetime(2026, 8, 30, 17, 39, 1, 500_000),
            )

        self.assertEqual(summary["yahoo_missing"], 0)
        self.assertFalse(
            any("COALESCE" in statement for statement, _ in fake_engine.connection.executed)
        )

    def test_fresh_dual_source_match_clears_a_prior_yahoo_missing_quarantine(self):
        fake_engine = _FakeEngine(
            [
                {
                    "id": 5,
                    "ticker": "AVGO",
                    "earning_at": datetime(2026, 9, 2),
                    "schedule_last_yahoo_seen_at": datetime(2026, 8, 30, 17, 38, 40),
                    "schedule_revalidation_reason": "yahoo_source_missing",
                }
            ]
        )
        with (
            mock.patch.object(schema, "ensure_schedule_time_schema"),
            mock.patch.object(connection, "engine", fake_engine),
        ):
            summary = database.reconcile_near_term_schedule_sources(
                [{"ticker": "AVGO", "earning_date": date(2026, 9, 2)}],
                yahoo_observed_at=datetime(2026, 8, 30, 17, 38, 40),
                nasdaq_fetched_dates={date(2026, 9, 2)},
                start_date=date(2026, 8, 30),
                days_ahead=14,
                observed_at=datetime(2026, 8, 30, 17, 39, 1),
            )

        self.assertEqual(summary["source_recovered"], 1)
        self.assertTrue(
            any(
                "schedule_revalidation_status = 'clear'" in statement
                for statement, _ in fake_engine.connection.executed
            )
        )

    def _real_schedule_row(self, call_id, event_date):
        engine = SQLiteScheduleEngine()
        with engine.raw.begin() as conn:
            conn.execute(text("""INSERT INTO calls
                (id, ticker, earning_at, call_year, quarter, scheduled_at_utc,
                 time_verification_status, source_timezone, time_verified_at)
                VALUES (:id, 'ACN', :event_date, 2026, 'Q3', :old_time,
                        'verified', 'America/New_York', '2026-09-01 01:00:00')"""),
                {'id': call_id, 'event_date': event_date, 'old_time': event_date + ' 12:00:00'})
        self.addCleanup(engine.raw.dispose)
        return engine

    def test_probe_date_mismatch_quarantines_the_call_for_official_revalidation(self):
        engine = self._real_schedule_row(8, '2026-09-02')
        with (mock.patch.object(schema, 'ensure_schedule_time_schema'),
              mock.patch.object(connection, 'engine', engine)):
            quarantined = database.quarantine_schedule_for_official_page_date_mismatch(
                8, expected_date=date(2026, 9, 2), observed_date=date(2026, 9, 9),
                error='EVENT_DATE_MISMATCH September 9, 2026')
        self.assertTrue(quarantined)
        with engine.raw.connect() as conn:
            row = conn.execute(text('SELECT * FROM calls WHERE id=8')).mappings().first()
        self.assertEqual(row['schedule_revalidation_status'], 'required')
        self.assertIsNone(row['scheduled_at_utc'])
        self.assertIn('"official_page_date": "2026-09-09"', row['schedule_revalidation_evidence'])

    def test_nearby_official_call_date_keeps_watch_and_invalidates_stale_time(self):
        engine = self._real_schedule_row(8, '2026-09-10')
        with (mock.patch.object(schema, 'ensure_schedule_time_schema'),
              mock.patch.object(connection, 'engine', engine)):
            quarantined = database.quarantine_schedule_for_official_page_date_mismatch(
                8, expected_date=date(2026, 9, 10), observed_date=date(2026, 9, 11),
                error='NOT_LIVE_YET September 11, 2026')
        self.assertFalse(quarantined)
        with engine.raw.connect() as conn:
            row = conn.execute(text('SELECT * FROM calls WHERE id=8')).mappings().first()
        self.assertEqual(row['webcast_date'], '2026-09-11')
        self.assertIsNone(row['scheduled_at_utc'])
        self.assertEqual(row['time_verification_status'], 'unverified')
        self.assertEqual(row['schedule_revalidation_status'], 'clear')

    def test_discovered_official_date_change_invalidates_stale_exact_time(self):
        engine = self._real_schedule_row(9, '2026-09-10')
        with (mock.patch.object(schema, 'ensure_schedule_time_schema'),
              mock.patch.object(connection, 'engine', engine)):
            database.update_official_schedule_discovery(
                9, webcast_date=date(2026, 9, 12), event_url='https://ir.example.com/events/q3',
                webcast_url='https://events.provider.example/123', source='official_ir_discovery',
                evidence='Q3 earnings webcast September 12, 2026', fingerprint='a' * 64)
        with engine.raw.connect() as conn:
            row = conn.execute(text('SELECT * FROM calls WHERE id=9')).mappings().first()
        self.assertEqual(row['webcast_date'], '2026-09-12')
        self.assertIsNone(row['scheduled_at_utc'])
        self.assertIsNone(row['source_timezone'])
        self.assertIsNone(row['time_verified_at'])


class ScheduleReconciliationOrchestrationTest(unittest.TestCase):
    def test_live_refresh_orders_yahoo_then_nasdaq_then_ir_verification(self):
        orchestrator = EarningsOrchestrator().schedules
        observed_at = datetime(2026, 8, 20, 9, 0)
        summary = {
            "nasdaq_events": 1,
            "source_matches": 1,
            "source_recovered": 0,
            "date_mismatches": 0,
            "yahoo_missing": 0,
            "nasdaq_only": 0,
        }
        with (
            mock.patch.object(orchestrator, "update_all_schedules", return_value=observed_at) as update,
            mock.patch.object(
                orchestrator,
                "reconcile_near_term_schedule_sources",
                return_value=summary,
            ) as reconcile,
            mock.patch.object(orchestrator, "enrich_schedule_times") as enrich,
        ):
            orchestrator.refresh_live_schedule_data()

        update.assert_called_once_with(max_workers=10)
        reconcile.assert_called_once_with(yahoo_observed_at=observed_at)
        enrich.assert_called_once_with(limit=20)

    def test_provisional_calls_remain_watchable_but_required_calls_are_excluded(self):
        candidate_query = inspect.getsource(database.get_date_based_stream_candidates)
        claim_query = inspect.getsource(database.claim_stream_probe)
        completion_query = inspect.getsource(database.update_verified_schedule_time)

        self.assertIn("'clear', 'provisional_watch'", candidate_query)
        self.assertIn("DATE_STREAM_UNCERTAIN_DATE_GRACE_DAYS", candidate_query)
        self.assertIn("c.scheduled_at_utc <= :window_end", candidate_query)
        self.assertIn("'clear', 'provisional_watch'", claim_query)
        self.assertIn("schedule_revalidation_status = 'clear'", completion_query)

    def test_official_date_confirmation_releases_only_the_watcher_quarantine(self):
        confirmation_query = inspect.getsource(
            database.confirm_schedule_revalidation_from_official_ir
        )

        self.assertIn("schedule_revalidation_status = 'clear'", confirmation_query)
        self.assertNotIn("time_verification_status = 'verified'", confirmation_query)


if __name__ == "__main__":
    unittest.main()
