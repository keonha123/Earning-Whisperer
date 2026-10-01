"""Issuer confirmation reconciles cross-quarter calendar guesses with provenance."""
from datetime import date, datetime, timedelta
import json
import unittest
from unittest import mock

from sqlalchemy import text

from data_pipeline.storage import schedules, schema
from data_pipeline.tests.test_schedule_revision_storage import SQLiteScheduleEngine


class CorroboratedScheduleAliasTest(unittest.TestCase):
    def setUp(self):
        self.engine = SQLiteScheduleEngine()
        self.addCleanup(self.engine.raw.dispose)
        self.now = datetime(2026, 9, 29, 3)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(schedules.connection, 'engine', self.engine).start()
        mock.patch.object(schema, 'ensure_schedule_time_schema').start()
        self.add(1, '2026-09-29', 'Q3', schedule_revalidation_status='provisional_watch',
                 schedule_revalidation_reason='date_mismatch',
                 schedule_revalidation_evidence=json.dumps({
                     'reason': 'date_mismatch', 'database_date': '2026-09-29',
                     'nasdaq_date': '2026-10-01', 'yahoo_observed_at': str(self.now)}),
                 schedule_last_nasdaq_seen_at=str(self.now - timedelta(hours=1)))
        self.add(2, '2026-10-01', 'Q4')

    def add(self, call_id, event_date, quarter, **values):
        data = {'id': call_id, 'ticker': 'EXAMPLE', 'earning_at': event_date,
                'call_year': 2026, 'quarter': quarter, **values}
        with self.engine.raw.begin() as conn:
            conn.execute(text('INSERT INTO calls (' + ','.join(data) + ') VALUES ('
                              + ','.join(':' + key for key in data) + ')'), data)

    def update(self, call_id, **values):
        with self.engine.raw.begin() as conn:
            conn.execute(text('UPDATE calls SET ' + ','.join(key + '=:' + key for key in values)
                              + ' WHERE id=:call_id'), {**values, 'call_id': call_id})

    def row(self, call_id):
        with self.engine.raw.connect() as conn:
            return dict(conn.execute(text('SELECT * FROM calls WHERE id=:id'),
                                     {'id': call_id}).mappings().first())

    def history(self):
        with self.engine.raw.connect() as conn:
            return [dict(row) for row in conn.execute(text('SELECT * FROM schedule_change_history')).mappings()]

    def verify(self, call_id=2, **extra):
        return schedules.update_verified_schedule_time(call_id, {
            'webcast_date': date(2026, 10, 1), 'scheduled_at_utc': datetime(2026, 10, 1, 21),
            'source_timezone': 'America/Los_Angeles',
            'event_url': 'https://issuer.test/events/fy2027-q1',
            'webcast_url': 'https://provider.test/event123',
            'schedule_source': 'official_ir_event', 'schedule_evidence': 'Q1 FY2027 earnings call',
            'event_identity': {'identity_verified': True, 'event_type': 'earnings_call',
                               'fiscal_year': 2027, 'fiscal_quarter': 'Q1',
                               'official_event_key': 'https://issuer.test/events/fy2027-q1'},
            'expected_revision': 0, 'observed_at': self.now, **extra})

    def test_new_bucket_confirmation_retires_wrong_day_with_audit_evidence(self):
        self.assertEqual(self.verify(), 1)
        old = self.row(1)
        self.assertEqual(old['schedule_superseded_by'], 2)
        self.assertEqual(old['earning_at'], '2026-09-29')
        self.assertEqual(old['schedule_revision'], 1)
        self.assertEqual(old['schedule_revalidation_status'], 'superseded')
        evidence = json.loads(old['schedule_revalidation_evidence'])
        self.assertEqual(evidence['source_correction']['nasdaq_date'], '2026-10-01')
        self.assertEqual(evidence['fiscal_quarter'], 'Q1')
        alias_history = next(row for row in self.history() if row['call_id'] == 1)
        self.assertEqual(alias_history['reason'], 'corroborated_calendar_duplicate')
        self.assertEqual(json.loads(alias_history['before_json'])['schedule_revalidation_reason'], 'date_mismatch')
        self.assertIsNotNone(json.loads(alias_history['before_json'])['schedule_revalidation_evidence'])

    def test_old_bucket_confirmation_keeps_its_id_and_retires_new_guess(self):
        self.assertEqual(self.verify(1), 1)
        self.assertIsNone(self.row(1)['schedule_superseded_by'])
        self.assertEqual(self.row(1)['webcast_date'], '2026-10-01')
        self.assertEqual(self.row(2)['schedule_superseded_by'], 1)

    def test_official_discovery_without_exact_clock_also_reconciles(self):
        payload = {'identity_verified': True, 'event_type': 'earnings_call',
                   'fiscal_year': 2027, 'fiscal_quarter': 'Q1'}
        schedules.update_official_schedule_discovery(
            2, webcast_date=date(2026, 10, 1), event_url='https://issuer.test/event',
            webcast_url=None, source='official_ir_discovery', evidence='Q1 FY2027 October 1',
            fingerprint='a' * 64, event_identity=payload, expected_revision=0, observed_at=self.now)
        self.assertEqual(self.row(1)['schedule_superseded_by'], 2)
        self.assertIsNone(self.row(2)['scheduled_at_utc'])

    def test_ticker_and_nearby_calendar_dates_alone_do_not_merge(self):
        self.update(1, schedule_revalidation_evidence=None)
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_missing_fiscal_identity_does_not_merge(self):
        self.verify(event_identity={'identity_verified': True, 'event_type': 'earnings_call'})
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_conflicting_verified_fiscal_identity_is_preserved(self):
        self.update(1, verified_fiscal_year=2026, verified_fiscal_quarter='Q4')
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_existing_official_route_is_not_treated_as_a_calendar_guess(self):
        self.update(1, event_url='https://issuer.test/events/other')
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_stale_or_future_nasdaq_evidence_does_not_merge(self):
        for seen in (self.now - timedelta(hours=49), self.now + timedelta(minutes=1)):
            with self.subTest(seen=seen):
                self.update(1, schedule_last_nasdaq_seen_at=str(seen))
                self.verify(expected_revision=int(self.row(2)['schedule_revision']))
                self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_newer_sibling_observation_is_preserved(self):
        self.update(1, schedule_observed_at=str(self.now + timedelta(minutes=1)))
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_wrong_mismatch_dates_do_not_merge(self):
        self.update(1, schedule_revalidation_evidence=json.dumps({
            'reason': 'date_mismatch', 'database_date': '2026-09-28', 'nasdaq_date': '2026-10-01'}))
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_distant_calendar_event_does_not_merge(self):
        self.update(1, earning_at='2026-07-01', schedule_revalidation_evidence=json.dumps({
            'reason': 'date_mismatch', 'database_date': '2026-07-01', 'nasdaq_date': '2026-10-01'}))
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_active_captured_or_completed_sibling_is_preserved(self):
        for values in ({'status': 'completed'}, {'status': 'running'}, {'status': 'live'},
                       {'stream_probe_status': 'probing'}, {'capture_attempts': 1},
                       {'capture_session_id': 'prior-session'}):
            with self.subTest(values=values):
                self.update(1, status='upcoming', stream_probe_status='pending',
                            capture_attempts=0, capture_session_id=None)
                self.update(1, **values)
                self.verify(expected_revision=int(self.row(2)['schedule_revision']))
                self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_outstanding_lease_is_preserved(self):
        self.update(1, capture_lease_owner='another-worker')
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_transcript_history_is_preserved(self):
        with self.engine.raw.begin() as conn:
            conn.execute(text("INSERT INTO transcript_segments VALUES ('1', 'preserve')"))
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_missing_source_observation_time_does_not_merge(self):
        self.update(1, schedule_last_nasdaq_seen_at=None)
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_source_correction_to_another_date_does_not_merge(self):
        self.update(1, schedule_revalidation_evidence=json.dumps({
            'reason': 'date_mismatch', 'database_date': '2026-09-29', 'nasdaq_date': '2026-10-02'}))
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_previously_captured_canonical_does_not_absorb_a_calendar_guess(self):
        self.update(2, capture_attempts=1)
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])

    def test_calendar_year_boundary_uses_same_corroboration(self):
        self.now = datetime(2026, 12, 29, 3)
        self.update(1, earning_at='2026-12-30', quarter='Q4',
                    schedule_revalidation_evidence=json.dumps({'reason': 'date_mismatch',
                       'database_date': '2026-12-30', 'nasdaq_date': '2027-01-01'}),
                    schedule_last_nasdaq_seen_at=str(self.now))
        self.update(2, earning_at='2027-01-01', call_year=2027, quarter='Q1')
        self.verify(webcast_date=date(2027, 1, 1), scheduled_at_utc=datetime(2027, 1, 1, 21))
        self.assertEqual(self.row(1)['schedule_superseded_by'], 2)
        self.assertEqual(self.row(1)['call_year'], 2026)
        self.assertEqual(self.row(2)['call_year'], 2027)

    def test_stale_incoming_revision_cannot_reconcile_any_sibling(self):
        self.update(2, schedule_revision=1)
        self.assertIsNone(self.verify())
        self.assertIsNone(self.row(1)['schedule_superseded_by'])
        self.assertEqual(self.history(), [])

    def test_multiple_plausible_siblings_are_left_for_revalidation(self):
        self.add(3, '2026-09-30', 'Q3', schedule_revalidation_reason='date_mismatch',
                 schedule_revalidation_evidence=json.dumps({'reason': 'date_mismatch',
                    'database_date': '2026-09-30', 'nasdaq_date': '2026-10-01'}),
                 schedule_last_nasdaq_seen_at=str(self.now))
        self.verify()
        self.assertIsNone(self.row(1)['schedule_superseded_by'])
        self.assertIsNone(self.row(3)['schedule_superseded_by'])

    def test_reconfirmation_is_idempotent(self):
        self.verify()
        self.verify(expected_revision=1, observed_at=self.now + timedelta(minutes=1))
        self.assertEqual(self.row(1)['schedule_revision'], 1)
        self.assertEqual(len([row for row in self.history() if row['call_id'] == 1]), 1)


if __name__ == '__main__':
    unittest.main()
