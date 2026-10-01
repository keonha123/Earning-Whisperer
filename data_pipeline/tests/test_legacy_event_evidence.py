"""Old contradictory event proof cannot freeze or authenticate a live call."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import unittest
from unittest import mock
from sqlalchemy import text

from data_pipeline.collectors.schedules.event_routes import route_proof, stored_event_kind_conflict
from data_pipeline.storage import schedules, live_calls
from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.tests import test_schedule_revision_storage as storage_fixture
from data_pipeline.tests import test_schedule_watch_freshness as query_fixture
from data_pipeline.tests import test_browser_schedule_storage as browser_fixture


class StoredEventKindTest(unittest.TestCase):
    def test_non_target_title_beats_old_typed_route(self):
        proof = route_proof(ticker='TEST', day=date(2026,9,30), issuer_url='https://issuer.test',
                            event_url='https://issuer.test/earnings-call', webcast_url='https://provider.test/123')
        for title in ('Post Earnings Analyst Call', 'Post-Earnings Analyst Call', 'Investor Day', 'Annual Shareholder Meeting'):
            with self.subTest(title=title):
                self.assertTrue(stored_event_kind_conflict(proof + ' ' + title))
        for title in ('Q4 earnings call September 30', 'Financial results conference call',
                      'Q4 earnings call with analyst questions',
                      'Q4 earnings call. Investor Day will follow next month.', ''):
            self.assertFalse(stored_event_kind_conflict(proof + ' ' + title), title)

    def test_current_and_remembered_handoff_reject_contradictory_title(self):
        now = datetime.now(timezone.utc)
        call = dict(id=1, ticker='TEST', earning_at=now.date(), ir_url='https://issuer.test',
                    event_url='https://issuer.test/earnings-call', webcast_url='https://provider.test/123',
                    schedule_revision=1, schedule_source='official_ir_event', schedule_revalidation_status='clear',
                    schedule_discovery_fingerprint='proof', schedule_discovery_checked_at=now)
        call['schedule_evidence'] = route_proof(ticker='TEST', day=now.date(), issuer_url=call['ir_url'],
            event_url=call['event_url'], webcast_url=call['webcast_url']) + ' Post Earnings Analyst Call'
        self.assertIsNone(STTWorkerManager._stored_target_proof(call))
        proof = dict(verified=True, call_id=1, call_ticker='TEST', target_date=str(now.date()),
                     schedule_revision=1, source_url=call['ir_url'], target_url=call['webcast_url'],
                     observed_at=now.isoformat(), evidence=call['schedule_evidence'])
        self.assertFalse(STTWorkerManager._fresh_discovery_proof(call, call['webcast_url'], proof))
        self.assertIsNone(STTWorkerManager._bound_route_proof(call, proof))


class LegacyEvidenceStorageTest(storage_fixture.ScheduleRevisionStorageTest):
    def setUp(self):
        super().setUp()
        self.bad = route_proof(ticker='ACN', day=date(2026,9,24), issuer_url='https://issuer.test',
            event_url='https://issuer.test/earnings-call', webcast_url='https://provider.test/123') + ' Post Earnings Analyst Call'
        self.update(schedule_source='official_ir_event', schedule_evidence=self.bad, schedule_revision=4,
                    scheduled_at_utc='2026-09-24 22:00:00', source_timezone='UTC',
                    time_verified_at=self.now, time_verification_status='verified',
                    event_url='https://issuer.test/earnings-call', webcast_url='https://provider.test/123',
                    schedule_discovery_fingerprint='old', schedule_revalidation_status='clear',
                    stream_probe_retry_reason='scheduled_start_wait', stream_probe_retry_not_before='2026-09-24 21:55:00')
        with self.engine.raw.begin() as c:
            c.execute(text("INSERT INTO stocks VALUES ('ACN','Test','https://issuer.test')"))

    def invalidate(self):
        return schedules.invalidate_non_earnings_schedule_evidence(reference_time_utc=self.now, days_ahead=14)

    def test_regular_enrichment_withdraws_bad_clock_with_history_without_network(self):
        rows = schedules.get_calls_missing_verified_time(reference_time_utc=self.now, days_ahead=14)
        self.assertEqual([r['id'] for r in rows], [1])
        row = self.row()
        self.assertEqual(row['schedule_revision'], 5)
        self.assertEqual(row['schedule_revalidation_reason'], 'stored_non_earnings_event')
        for key in ('scheduled_at_utc','event_url','webcast_url','schedule_discovery_fingerprint',
                    'stream_probe_retry_not_before','stream_probe_retry_reason'):
            self.assertIsNone(row[key],key)
        self.assertEqual(self.history()[0]['reason'], 'stored_non_earnings_event')
        self.assertIn('Post Earnings Analyst Call', self.history()[0]['before_json'])
        self.assertEqual(self.invalidate(),0)

    def test_auth_and_enrichment_retry_gates_survive_withdrawal(self):
        retry='2026-09-24 18:00:00'
        self.update(stream_probe_retry_reason='auth_required', stream_probe_retry_not_before=retry,
                    schedule_enrichment_retry_not_before=retry, schedule_enrichment_failure_kind='issuer_browser_access_denied',
                    capture_retry_not_before=retry)
        self.assertEqual(self.invalidate(),1)
        row=self.row()
        for key in ('stream_probe_retry_not_before','schedule_enrichment_retry_not_before','capture_retry_not_before'):
            self.assertEqual(row[key],retry)
        self.assertEqual(row['stream_probe_retry_reason'],'auth_required')

    def test_active_captured_completed_and_leased_records_are_preserved(self):
        original=self.row()
        for values in ({'status':'running'}, {'status':'completed'}, {'status':'ended'},
                       {'stream_probe_status':'probing'}, {'capture_attempts':1},
                       {'capture_session_id':'archived-session'}, {'capture_lease_owner':'owner'},
                       {'stream_probe_lease_owner':'owner'}, {'stream_probe_lease_until':self.now+timedelta(minutes=1)},
                       {'schedule_superseded_by':2}, {'schedule_observed_at':self.now+timedelta(seconds=1)}):
            with self.subTest(values=values):
                self.update(**original);self.update(**values)
                before=self.row();self.assertEqual(self.invalidate(),0);self.assertEqual(self.row(),before)
        self.assertEqual(self.history(),[])

    def test_transcript_history_is_preserved(self):
        with self.engine.raw.begin() as c:
            c.execute(text("INSERT INTO transcript_segments VALUES ('1','historic transcript')"))
        self.assertEqual(self.invalidate(),0)
        self.assertEqual(self.row()['schedule_revision'],4)

    def test_snapshot_revision_race_does_not_overwrite_new_schedule(self):
        connect=self.engine.connect
        @contextmanager
        def raced_connect():
            with connect() as conn:
                yield conn
            self.update(schedule_revision=5, schedule_evidence='Q4 earnings call')
        with mock.patch.object(self.engine,'connect',raced_connect):
            self.assertEqual(self.invalidate(),0)
        self.assertEqual(self.row()['schedule_evidence'],'Q4 earnings call')
        self.assertEqual(self.history(),[])

    def test_new_non_earnings_time_cannot_be_saved(self):
        self.assertIsNone(self.verify(expected_revision=4, schedule_evidence=self.bad))
        self.assertEqual(self.row()['schedule_revision'],4)

    def test_genuine_earnings_schedule_is_unchanged(self):
        self.update(schedule_evidence=self.bad.replace('Post Earnings Analyst Call', 'Q4 Earnings Call'))
        before=self.row();self.assertEqual(self.invalidate(),0);self.assertEqual(self.row(),before)


class StaleWaitQueryTest(query_fixture.ScheduleWatchFreshnessTest):
    def test_stale_scheduled_wait_cannot_hide_today(self):
        self.add_call('OLD', scheduled_at_utc=datetime(2026,9,17,21),
            time_verified_at=(self.now-timedelta(hours=3)).replace(tzinfo=None),
            stream_probe_retry_reason='scheduled_start_wait', stream_probe_retry_not_before=datetime(2026,9,17,20,55))
        self.assertEqual(self.candidates(),['OLD'])

    def test_fresh_scheduled_wait_and_stale_auth_remain_gated(self):
        for ticker,age,reason in [('FRESH',1,'scheduled_start_wait'),('AUTH',3,'auth_required'),('BLOCK',3,'access_blocked')]:
            self.add_call(ticker, scheduled_at_utc=self.now.replace(tzinfo=None),
                time_verified_at=(self.now-timedelta(hours=age)).replace(tzinfo=None),
                stream_probe_retry_reason=reason, stream_probe_retry_not_before=(self.now+timedelta(hours=1)).replace(tzinfo=None))
        self.assertEqual(self.candidates(),[])


class StaleWaitClaimTest(browser_fixture.BrowserScheduleStorageTest):
    def test_stale_scheduled_wait_can_be_claimed_but_auth_cannot(self):
        for reason,expected in [('scheduled_start_wait',True),('auth_required',False),('access_blocked',False)]:
            self.update(stream_probe_status='pending', stream_probe_lease_owner=None, stream_probe_lease_until=None,
                scheduled_at_utc=self.now+timedelta(hours=2), time_verification_status='verified',
                time_verified_at=self.now-timedelta(hours=3),
                last_stream_probe_at=self.now-timedelta(minutes=20),
                stream_probe_retry_not_before=self.now+timedelta(hours=2), stream_probe_retry_reason=reason)
            self.assertEqual(live_calls.claim_stream_probe(1,expected_schedule_revision=7),expected)

    def test_stale_clock_does_not_reimpose_future_wait_after_probe(self):
        self.update(scheduled_at_utc=self.now+timedelta(hours=2),time_verification_status='verified',
                    time_verified_at=self.now-timedelta(hours=3))
        result=live_calls.record_stream_probe(1,False,
            error='NOT_LIVE_YET scheduled event time is in the future: 2035-09-22T19:00:00Z',
            expected_date=self.now.date(),expected_schedule_revision=7,watch_state='date_only')
        self.assertEqual(result['reason'],'transient_error')
        self.assertEqual(self.row()['stream_probe_retry_not_before'],'2035-09-22 12:01:00')


for cls,base in ((LegacyEvidenceStorageTest,storage_fixture.ScheduleRevisionStorageTest),
                 (StaleWaitQueryTest,query_fixture.ScheduleWatchFreshnessTest),
                 (StaleWaitClaimTest,browser_fixture.BrowserScheduleStorageTest)):
    for name in dir(base):
        if name.startswith('test_') and name not in cls.__dict__:
            setattr(cls,name,None)
