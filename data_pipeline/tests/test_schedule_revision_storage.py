"""Real SQL behavior for schedule changes (SQLite strips only row-lock syntax)."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
import unittest
from unittest import mock

from sqlalchemy import create_engine, text

from data_pipeline.storage import schedules, schema


class _SQLiteConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, params=None):
        return self.connection.execute(text(str(statement).replace(' FOR UPDATE', '')), params or {})


class SQLiteScheduleEngine:
    """No business logic emulation: only unsupported SELECT locking is removed."""
    def __init__(self):
        self.raw = create_engine('sqlite:///:memory:')
        with self.raw.begin() as conn:
            fields = ', '.join(f'{name} {definition}' for name, definition in schema.SCHEDULE_TIME_COLUMNS.items())
            conn.execute(text('CREATE TABLE calls (id INTEGER PRIMARY KEY, ticker TEXT, '
                              'earning_at DATETIME, call_year INTEGER, quarter TEXT, '
                              "status TEXT DEFAULT 'upcoming', video_url TEXT, " + fields + ')'))
            conn.execute(text('CREATE TABLE transcript_segments (call_id TEXT, text_chunk TEXT)'))
            conn.execute(text('CREATE TABLE schedule_change_history ('
                              'id INTEGER PRIMARY KEY, call_id INTEGER, revision INTEGER, '
                              'reason TEXT, observed_at DATETIME, before_json TEXT, after_json TEXT)'))
            conn.execute(text('CREATE TABLE stocks (ticker TEXT, company_name TEXT, ir_url TEXT)'))

    @contextmanager
    def begin(self):
        with self.raw.begin() as conn:
            yield _SQLiteConnection(conn)

    @contextmanager
    def connect(self):
        with self.raw.connect() as conn:
            yield _SQLiteConnection(conn)


class ScheduleRevisionStorageTest(unittest.TestCase):
    def setUp(self):
        self.engine = SQLiteScheduleEngine()
        self.stack = mock.patch.object(schedules.connection, 'engine', self.engine)
        self.stack.start()
        self.schema_patch = mock.patch.object(schema, 'ensure_schedule_time_schema')
        self.schema_patch.start()
        self.now = datetime(2026, 9, 18, 1)
        self.add_call(1)

    def tearDown(self):
        self.schema_patch.stop()
        self.stack.stop()
        self.engine.raw.dispose()

    def add_call(self, call_id, **values):
        data = {'id': call_id, 'ticker': 'ACN', 'earning_at': '2026-09-24',
                'call_year': 2026, 'quarter': 'Q3', **values}
        with self.engine.raw.begin() as conn:
            conn.execute(text('INSERT INTO calls (' + ','.join(data) + ') VALUES ('
                              + ','.join(':' + key for key in data) + ')'), data)

    def row(self, call_id=1):
        with self.engine.raw.connect() as conn:
            return dict(conn.execute(text('SELECT * FROM calls WHERE id=:id'), {'id': call_id}).mappings().first())

    def update(self, **values):
        with self.engine.raw.begin() as conn:
            conn.execute(text('UPDATE calls SET ' + ','.join(key + '=:' + key for key in values)
                              + ' WHERE id=1'), values)

    def history(self):
        with self.engine.raw.connect() as conn:
            return [dict(row) for row in conn.execute(text('SELECT * FROM schedule_change_history ORDER BY id')).mappings()]

    @staticmethod
    def identity(**extra):
        return {'fiscal_year': 2026, 'fiscal_quarter': 'Q4', 'event_type': 'earnings_call',
                'official_event_key': 'https://issuer.test/events/fy2026-q4',
                'identity_verified': True, 'date_shift_verified': True, **extra}

    def verify(self, call_id=1, **extra):
        payload = {'webcast_date': date(2026, 10, 1),
                   'scheduled_at_utc': datetime(2026, 10, 1, 12),
                   'source_timezone': 'America/New_York',
                   'event_url': 'https://issuer.test/events/fy2026-q4',
                   'webcast_url': 'https://webcast.test/abc',
                   'schedule_source': 'official_ir_event',
                   'schedule_evidence': 'FY2026 Q4 earnings call October 1 at 8 a.m. ET',
                   'event_identity': self.identity(), 'expected_revision': 0,
                   'observed_at': self.now, **extra}
        return schedules.update_verified_schedule_time(call_id, payload)

    def test_cross_calendar_quarter_change_retains_call_id_and_legacy_bucket(self):
        self.assertEqual(self.verify(), 1)
        row = self.row()
        self.assertEqual((row['id'], row['call_year'], row['quarter']), (1, 2026, 'Q3'))
        self.assertEqual((row['verified_fiscal_year'], row['verified_fiscal_quarter']), (2026, 'Q4'))
        self.assertEqual(row['webcast_date'], '2026-10-01')
        history = self.history()
        self.assertEqual(len(history), 1)
        self.assertIsNone(json.loads(history[0]['before_json'])['scheduled_at_utc'])
        self.assertEqual(json.loads(history[0]['after_json'])['scheduled_at_utc'], '2026-10-01 12:00:00')

    def test_large_date_shift_requires_positive_same_event_proof(self):
        self.assertIsNone(self.verify(event_identity=None))
        self.assertIsNone(self.verify(event_identity=self.identity(date_shift_verified=False)))
        self.assertEqual(self.history(), [])

    def test_old_revision_and_old_observation_cannot_overwrite_new_time(self):
        self.verify()
        self.assertIsNone(self.verify(scheduled_at_utc=datetime(2026, 10, 1, 13), observed_at=self.now + timedelta(minutes=2)))
        self.assertIsNone(self.verify(expected_revision=1, observed_at=self.now - timedelta(minutes=1)))
        self.assertEqual(self.row()['scheduled_at_utc'], '2026-10-01 12:00:00')
        self.assertEqual(len(self.history()), 1)

    def test_identical_reconfirmation_advances_observation_without_new_revision(self):
        self.verify()
        self.assertEqual(self.verify(expected_revision=1, observed_at=self.now + timedelta(minutes=10)), 1)
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.row()['time_verified_at'], '2026-09-18 01:10:00')

    def test_active_probe_capture_and_completed_rows_are_never_rewritten(self):
        for status, probe in [('upcoming', 'probing'), ('running', 'found'), ('completed', 'found')]:
            with self.subTest(status=status, probe=probe):
                self.update(status=status, stream_probe_status=probe)
                self.assertIsNone(self.verify())
                schedules.confirm_schedule_revalidation_from_official_ir(1, event_url='https://issuer.test', evidence='date', webcast_date=date(2026, 9, 24))
                schedules.record_schedule_enrichment_outcome(1, failure_kind='ambiguous_call_time', error='two times', retry_minutes=1)
                self.assertEqual(self.row()['schedule_revision'], 0)
        self.assertEqual(self.history(), [])

    def test_time_change_invalidates_retry_and_cached_playback(self):
        self.verify()
        self.update(video_url='https://old.test/audio', stream_probe_status='found', stream_probe_attempts=7,
                    stream_probe_retry_not_before='2026-10-01 16:00:00', stream_probe_retry_reason='waiting',
                    schedule_discovery_fingerprint='old', capture_retry_not_before='2026-10-01 16:00:00')
        self.assertEqual(self.verify(expected_revision=1, observed_at=self.now + timedelta(minutes=1),
                                     scheduled_at_utc=datetime(2026, 10, 1, 13)), 2)
        row = self.row()
        for field in ('video_url', 'stream_probe_retry_not_before', 'stream_probe_retry_reason',
                      'schedule_discovery_fingerprint', 'capture_retry_not_before'):
            self.assertIsNone(row[field], field)
        self.assertEqual((row['stream_probe_status'], row['stream_probe_attempts']), ('pending', 0))

    def test_confirmed_no_time_withdraws_old_exact_but_network_error_does_not(self):
        self.verify()
        schedules.record_schedule_enrichment_outcome(1, failure_kind='http_unavailable', error='503', retry_minutes=10,
                                                     expected_revision=1, observed_at=self.now + timedelta(minutes=1))
        self.assertEqual(self.row()['scheduled_at_utc'], '2026-10-01 12:00:00')
        result = schedules.confirm_schedule_revalidation_from_official_ir(
            1, event_url='https://issuer.test/events/fy2026-q4', evidence='October 1 time to be announced',
            webcast_date=date(2026, 10, 1), expected_revision=1, observed_at=self.now + timedelta(minutes=2))
        self.assertEqual(result, 2)
        self.assertIsNone(self.row()['scheduled_at_utc'])
        self.assertEqual(self.row()['webcast_date'], '2026-10-01')
        self.assertIsNotNone(self.row()['official_event_identity'])

    def test_reconfirmed_ambiguity_returns_to_provisional_date_watch(self):
        self.verify()
        schedules.record_schedule_enrichment_outcome(1, failure_kind='ambiguous_call_time', error='two start times',
                                                     retry_minutes=5, expected_revision=1, observed_at=self.now + timedelta(minutes=1))
        self.assertIsNone(self.row()['scheduled_at_utc'])
        self.assertEqual(self.row()['schedule_revalidation_status'], 'provisional_watch')

    def test_official_identity_deduplicates_cross_quarter_candidate_without_deleting(self):
        self.verify()
        self.add_call(2, earning_at='2026-10-01', quarter='Q4')
        self.assertIsNone(self.verify(2))
        self.assertEqual(self.row(2)['schedule_superseded_by'], 1)
        self.assertEqual(self.row(2)['schedule_revalidation_status'], 'superseded')
        self.assertEqual(self.row()['webcast_date'], '2026-10-01')
        self.assertIn('duplicate_official_event', [item['reason'] for item in self.history()])

    def test_newer_duplicate_observation_updates_canonical_time_atomically(self):
        self.verify()
        self.add_call(2, earning_at='2026-10-01', quarter='Q4')
        self.assertIsNone(self.verify(2, scheduled_at_utc=datetime(2026, 10, 1, 13),
                                     observed_at=self.now + timedelta(minutes=1)))
        self.assertEqual(self.row(2)['schedule_superseded_by'], 1)
        self.assertEqual(self.row()['scheduled_at_utc'], '2026-10-01 13:00:00')
        self.assertEqual(self.row()['schedule_revision'], 2)

    def test_calendar_dates_alone_do_not_merge_distinct_events(self):
        self.verify()
        self.add_call(2, earning_at='2026-10-01', quarter='Q4')
        self.assertEqual(self.verify(2, event_identity=None), 1)
        self.assertIsNone(self.row(2)['schedule_superseded_by'])

    def test_duplicate_with_capture_or_transcript_is_not_suppressed(self):
        self.verify()
        self.add_call(2, earning_at='2026-10-01', quarter='Q4', capture_attempts=1)
        self.assertEqual(self.verify(2), 1)
        self.assertIsNone(self.row(2)['schedule_superseded_by'])
        self.add_call(3, earning_at='2026-10-01', quarter='Q4')
        with self.engine.raw.begin() as conn:
            conn.execute(text("INSERT INTO transcript_segments VALUES ('3', 'preserve')"))
        self.assertEqual(self.verify(3), 1)
        self.assertIsNone(self.row(3)['schedule_superseded_by'])

    def test_conflicting_verified_fiscal_identity_is_rejected_even_with_same_url(self):
        self.verify()
        self.assertIsNone(self.verify(expected_revision=1, event_identity=self.identity(fiscal_quarter='Q1', fiscal_year=2027)))
        self.assertEqual(self.row()['verified_fiscal_quarter'], 'Q4')

    def test_discovery_changed_day_invalidates_time_inside_transaction(self):
        self.verify()
        self.assertEqual(schedules.update_official_schedule_discovery(
            1, webcast_date=date(2026, 10, 2), event_url='https://issuer.test/events/fy2026-q4',
            webcast_url='https://webcast.test/new', source='official_ir_discovery', evidence='Moved to October 2',
            fingerprint='a' * 64, event_identity=self.identity(), expected_revision=1,
            observed_at=self.now + timedelta(minutes=1)), 2)
        self.assertIsNone(self.row()['scheduled_at_utc'])
        self.assertEqual(self.row()['schedule_discovery_fingerprint'], 'a' * 64)

    def test_stale_probe_date_mismatch_cannot_quarantine_new_schedule(self):
        self.verify()
        self.assertFalse(schedules.quarantine_schedule_for_official_page_date_mismatch(
            1, expected_date=date(2026, 9, 24), observed_date=date(2026, 9, 30), error='stale probe'))
        self.assertEqual(self.row()['schedule_revalidation_status'], 'clear')

    def test_generic_reused_event_url_does_not_merge_conflicting_fiscal_periods(self):
        generic = 'https://issuer.test/earnings-webcast'
        self.verify(event_url=generic, event_identity=self.identity(official_event_key=generic))
        self.add_call(2, earning_at='2026-10-01', quarter='Q4')
        self.assertEqual(self.verify(2, event_url=generic, event_identity=self.identity(
            official_event_key=generic, fiscal_year=2027, fiscal_quarter='Q1')), 1)
        self.assertIsNone(self.row(2)['schedule_superseded_by'])

    def test_verified_time_can_atomically_persist_fresh_typed_route(self):
        self.assertEqual(self.verify(schedule_discovery_fingerprint='a' * 64), 1)
        self.assertEqual(self.row()['schedule_discovery_fingerprint'], 'a' * 64)
        self.assertEqual(self.row()['schedule_discovery_checked_at'], str(self.now))

    def test_same_page_discovery_then_time_preserves_fresh_route_proof(self):
        discovery = schedules.update_official_schedule_discovery(
            1, webcast_date=date(2026, 10, 1), event_url='https://issuer.test/events/fy2026-q4',
            webcast_url='https://webcast.test/abc', source='official_ir_discovery', evidence='October 1',
            fingerprint='f' * 64, event_identity=self.identity(), expected_revision=0, observed_at=self.now)
        self.assertEqual(self.verify(expected_revision=discovery), 2)
        self.assertEqual(self.row()['schedule_discovery_fingerprint'], 'f' * 64)
        self.assertEqual(self.row()['schedule_discovery_checked_at'], str(self.now))

    def test_confirmed_cancellation_stops_watch_and_postponement_keeps_date_watch(self):
        self.verify()
        schedules.record_schedule_enrichment_outcome(1, failure_kind='official_cancelled', error='cancelled',
                                                     retry_minutes=5, expected_revision=1, observed_at=self.now + timedelta(minutes=1))
        self.assertIsNone(self.row()['scheduled_at_utc'])
        self.assertEqual(self.row()['schedule_revalidation_status'], 'cancelled')
        schedules.record_schedule_enrichment_outcome(1, failure_kind='official_postponed', error='postponed',
                                                     retry_minutes=5, expected_revision=2, observed_at=self.now + timedelta(minutes=2))
        self.assertEqual(self.row()['schedule_revalidation_status'], 'provisional_watch')

    def test_schedule_context_exposes_verified_identity_and_revision(self):
        self.verify()
        with self.engine.raw.begin() as conn:
            conn.execute(text("INSERT INTO stocks VALUES ('ACN', 'Accenture', 'https://issuer.test')"))
        row = schedules.get_call_schedule_context(1)
        self.assertEqual(row['schedule_revision'], 1)
        self.assertEqual(row['quarter'], 'Q3')
        self.assertEqual(row['verified_fiscal_quarter'], 'Q4')


if __name__ == '__main__':
    unittest.main()
