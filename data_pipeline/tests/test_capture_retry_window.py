"""Actual candidate SQL must not recycle old captures after clock expiry."""
from datetime import datetime, timedelta, timezone
import os
from unittest import mock

from data_pipeline.application.settings import probe_window
from data_pipeline.storage import live_calls, policies
from data_pipeline.tests import test_live_schedule_timing as fixture


class CaptureRetryWindowTests(fixture.LiveScheduleQueryTest):
    def setUp(self):
        super().setUp()
        self.environment = mock.patch.dict(os.environ, {
            'DATE_STREAM_WATCH_TIMEZONE': 'America/New_York',
            'DATE_STREAM_NEAR_END_MINUTES': '180'}, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_old_capture_does_not_reenter_when_exact_clock_loses_freshness(self):
        self.add_call('PAST', scheduled_at_utc=self.now-timedelta(hours=10),
                      time_verified_at=self.now-timedelta(hours=5),
                      capture_attempts=1, capture_session_id='previous-session')
        self.assertEqual(self.candidates(), [])

    def test_unknown_clock_old_capture_does_not_recycle_previous_days(self):
        self.add_call('PAST', webcast_date=(self.now-timedelta(days=1)).date(),
                      schedule_revalidation_status='provisional_watch',
                      capture_attempts=1, capture_session_id='previous-session')
        self.assertEqual(self.candidates(), [])

    def test_first_discovery_with_stale_clock_still_allows_official_correction(self):
        self.add_call('FIRST', scheduled_at_utc=self.now-timedelta(hours=10),
                      time_verified_at=self.now-timedelta(hours=5),capture_attempts=0)
        self.assertEqual(self.candidates(), ['FIRST'])

    def test_reconnection_in_event_window_and_verified_reschedule_remain_possible(self):
        self.add_call('RETRY', scheduled_at_utc=self.now-timedelta(minutes=80),
                      capture_attempts=3, capture_session_id='earlier-connection')
        self.assertEqual(self.candidates(), ['RETRY'])

    def test_expired_rows_cannot_starve_the_next_call_via_sql_limit(self):
        for number in range(25):
            self.add_call(f'OLD{number}', scheduled_at_utc=self.now-timedelta(hours=10),
                          time_verified_at=self.now-timedelta(hours=5),capture_attempts=2)
        self.add_call('LIVE', scheduled_at_utc=self.now)
        rows=live_calls.get_date_based_stream_candidates(reference_time_utc=self.now,limit=1)
        self.assertEqual([r['ticker'] for r in rows], ['LIVE'])

    def test_unknown_time_allows_midnight_continuation_but_has_bound(self):
        call={'earning_at':'2026-09-17','capture_session_id':'previous'}
        self.assertFalse(policies.capture_retry_window(call,now=datetime(2026,9,18,5,tzinfo=timezone.utc))['expired'])
        self.assertTrue(policies.capture_retry_window(call,now=datetime(2026,9,18,8,tzinfo=timezone.utc))['expired'])
        self.add_call('LATE', earning_at=datetime(2026,9,17), capture_attempts=1,
                      capture_session_id='previous')
        rows=live_calls.get_date_based_stream_candidates(reference_time_utc=datetime(2026,9,18,5,tzinfo=timezone.utc))
        self.assertEqual([r['ticker'] for r in rows],['LATE'])
        rows=live_calls.get_date_based_stream_candidates(reference_time_utc=datetime(2026,9,18,8,tzinfo=timezone.utc))
        self.assertEqual(rows,[])

    def test_stale_snapshot_guard_uses_history_even_when_clock_is_ignored(self):
        now=self.now
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)
        call={'scheduled_at_utc':self.now-timedelta(hours=10),'schedule_time_stale':True,
              'capture_session_id':'previous','earning_at':self.now.date()}
        with mock.patch('data_pipeline.application.settings.datetime',Clock):
            self.assertEqual(probe_window(call,1)[0],'capture_retry_window_expired')

    def test_unknown_end_has_bounded_retry_but_other_live_faults_still_reconnect(self):
        with mock.patch.dict(os.environ,{},clear=True):
            idle=policies.capture_retry_policy('LIVE_CAPTURE_INCOMPLETE live_speech_idle_timeout',attempts=3)
            self.assertEqual((idle['reason'],idle['max_attempts']),('speech_idle_retry_limit',3))
            transient=policies.capture_retry_policy('LIVE_CAPTURE_INCOMPLETE PCM source lost',attempts=3)
            self.assertEqual(transient['max_attempts'],0)


for name in dir(fixture.LiveScheduleQueryTest):
    if name.startswith('test_') and name not in CaptureRetryWindowTests.__dict__:
        setattr(CaptureRetryWindowTests,name,None)
