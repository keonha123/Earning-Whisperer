"""Regression of omitted ACN/MKC attempts and progress-based local alerts."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from data_pipeline.operations import build_daily_report, check_operational_alerts, record_event
from data_pipeline.operations_progress import probe_outcomes, progress_issues, annotate_waiting_observation
from data_pipeline.application.live_watch import LiveWatchService

NOW = datetime(2026, 10, 1, 12, 10, tzinfo=timezone.utc)


def call(**changes):
    return {'id': 528, 'ticker': 'ACN', 'schedule_revision': 2, 'status': 'upcoming',
            'scheduled_at_utc': NOW-timedelta(minutes=10), 'capture_session_id': 'current-session',
            'last_text_at': None, **changes}


def failed(index, **changes):
    return {'event_type': 'probe_result', 'call_id': 528, 'ticker': 'ACN', 'schedule_revision': 2,
            'attempt_id': str(index), 'timestamp': (NOW-timedelta(minutes=3-index)).isoformat(),
            'status': 'pending', 'error': 'FORM_AUTOMATION_FAILED',
            'error_code': 'FORM_AUTOMATION_FAILED', 'failure_stage': 'registration',
            'failure_signature': 'same-form-failure', 'next_action': 'repair_form_and_retry', **changes}


class AttemptAccountingTest(unittest.TestCase):
    def test_actual_94_acn_37_mkc_legacy_attempts_remain_visible(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/operations_acn_mkc_20261001.json').read_text())
        events = [dict(zip(fixture['columns'], row)) for row in fixture['events']]
        results = probe_outcomes(events)
        acn = [r for r in results if r['ticker'] == 'ACN']
        mkc = [r for r in results if r['ticker'] == 'MKC']
        self.assertEqual(len(acn), 94)
        self.assertEqual(len(mkc), 37)
        self.assertTrue(all(r['outcome'] == 'unknown' for r in acn))
        self.assertEqual(sum(r['outcome'] == 'unknown' for r in mkc), 36)
        self.assertEqual(sum(r['outcome'] == 'deferred' for r in mkc), 1)
        self.assertFalse(any(r['outcome'] == 'audio_ready' for r in results))
        # Replay actual final-route outcomes through the new canonical event.
        # Earlier routes can have different root causes; this preserves only
        # what the source evidence actually establishes.
        modern = []
        for row in fixture['route_results']:
            modern.extend([row, {**row, 'event_type':'capture_skipped', 'error_code':'NONE'}])
        rebuilt = probe_outcomes(modern)
        self.assertEqual(len(rebuilt), 131)
        self.assertEqual(sum(r['outcome'] == 'failed' for r in rebuilt), 125)
        self.assertEqual(sum(r['outcome'] == 'waiting' for r in rebuilt), 6)

    def test_duplicate_attempt_results_count_once_and_waiting_is_not_failure(self):
        rows = [failed(1), failed(1), failed(2, error='NOT_LIVE_YET', error_code='NOT_LIVE_YET'),
                failed(3, error=None, error_code='NONE', status='deferred')]
        result = probe_outcomes(rows)
        self.assertEqual([r['outcome'] for r in result], ['failed', 'waiting', 'deferred'])

    def test_report_displays_unknown_separately_from_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPERATIONS_LOG_DIR':tmp}):
            record_event('probe_started', call_id=1, ticker='ACN')
            record_event('capture_skipped', call_id=1, ticker='ACN', status='schedule_changed_or_claimed')
            report = build_daily_report()
        self.assertEqual(report['probe_count'], 1)
        self.assertEqual(report['probe_unknown_count'], 1)
        self.assertEqual(report['probe_success_count'], 0)
        self.assertEqual(report['probe_failure_count'], 0)
        self.assertFalse(report['live_capture_success_assessed'])


class ProgressDecisionTest(unittest.TestCase):
    def test_three_identical_failures_and_no_text_are_actionable_for_one_call(self):
        rows = probe_outcomes([failed(i) for i in range(3)])
        issues = progress_issues(rows, [call()], now=NOW)
        self.assertEqual(len(issues), 2)
        repeat = issues[0]
        self.assertEqual(repeat['count'], 3)
        self.assertEqual(repeat['failure_stage'], 'registration')
        self.assertEqual(issues[1]['state'], 'no_durable_text_progress')

    def test_new_revision_and_recent_text_clear_old_failure_streak(self):
        rows = probe_outcomes([failed(i) for i in range(3)])
        self.assertEqual(progress_issues(rows, [call(schedule_revision=3, last_text_at=NOW)], now=NOW), [])
        self.assertEqual(progress_issues(rows, [call(last_text_at=NOW)], now=NOW), [])

    def test_audio_ready_interrupts_failure_streak_but_is_not_saved_text(self):
        rows = probe_outcomes([failed(i) for i in range(3)] + [failed(3, error=None, error_code='NONE', status='stream_ready')])
        issues = progress_issues(rows, [call()], now=NOW)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['state'], 'no_durable_text_progress')

    def test_prestart_waiting_and_music_dont_raise_failure_alarm(self):
        rows = probe_outcomes([failed(i, error='NOT_LIVE_YET', error_code='NOT_LIVE_YET') for i in range(3)])
        self.assertEqual(progress_issues(rows, [call()], now=NOW), [])
        self.assertEqual(progress_issues([], [call(waiting_observed=True)], now=NOW), [])
        self.assertEqual(progress_issues([], [call(scheduled_at_utc=NOW+timedelta(minutes=5))], now=NOW), [])

    def test_long_waiting_requests_schedule_review_without_claiming_failure(self):
        issues = progress_issues([], [call(waiting_observed=True, scheduled_at_utc=NOW-timedelta(minutes=20))], now=NOW)
        self.assertEqual(issues[0]['state'], 'waiting_beyond_expected_start')
        self.assertFalse(issues[0]['capture_failed'])
        self.assertEqual(issues[0]['severity'], 'warning')

    def test_completed_or_old_event_cannot_keep_alerting(self):
        rows = probe_outcomes([failed(i) for i in range(3)])
        self.assertEqual(progress_issues(rows, [call(status='completed')], now=NOW), [])
        self.assertEqual(progress_issues([], [call(scheduled_at_utc=NOW-timedelta(hours=4))], now=NOW), [])

    def test_date_only_is_not_assumed_to_have_started(self):
        self.assertEqual(progress_issues([], [call(scheduled_at_utc=None)], now=NOW), [])

    def test_waiting_evidence_must_be_fresh_same_session_and_revision(self):
        with tempfile.TemporaryDirectory() as tmp, patch('data_pipeline.live_runtime.runtime_root', return_value=Path(tmp)):
            p=Path(tmp)/'live-runs/528/attempt';p.mkdir(parents=True)
            row={'stage':'stt','status':'waiting_for_speech','speech_seen':False,'timestamp_utc':NOW.isoformat(),
                 'call_id':528,'schedule_revision':2,'capture_session_id':'current-session'}
            (p/'stt.json').write_text(json.dumps(row))
            self.assertTrue(annotate_waiting_observation(call(),now=NOW)['waiting_observed'])
            self.assertFalse(annotate_waiting_observation(call(schedule_revision=3),now=NOW)['waiting_observed'])
            self.assertFalse(annotate_waiting_observation(call(capture_session_id='another'),now=NOW)['waiting_observed'])
            self.assertFalse(annotate_waiting_observation(call(),now=NOW+timedelta(minutes=3))['waiting_observed'])


class LocalAlertTest(unittest.TestCase):
    def test_no_webhook_still_records_current_local_status_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'OPERATIONS_LOG_DIR':tmp,'OPERATIONS_ALERT_STATE_FILE':str(Path(tmp)/'state.json'),
                'OPERATIONS_ALERT_WEBHOOK_URL':''}), patch('data_pipeline.operations._utc_now',return_value=NOW), \
                patch('data_pipeline.operations._post_alert') as post:
            alerts=check_operational_alerts({'live_calls':[call()]})
            self.assertEqual(len(alerts),1)
            self.assertFalse(alerts[0]['external_notification_sent'])
            self.assertEqual(alerts[0]['notification_mode'],'local_only')
            self.assertEqual(check_operational_alerts({'live_calls':[call()]}),[])
            state=json.loads((Path(tmp)/'state.json').read_text())
            self.assertTrue(state['active'])
            check_operational_alerts({'live_calls':[call(last_text_at=NOW)]})
            state=json.loads((Path(tmp)/'state.json').read_text())
            self.assertFalse(state['active'])
            post.assert_not_called()

    def test_resource_capacity_alarm_precedes_any_new_browser_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'OPERATIONS_LOG_DIR':tmp,'OPERATIONS_ALERT_STATE_FILE':str(Path(tmp)/'state.json'),
                'OPERATIONS_ALERT_WEBHOOK_URL':''}), patch('data_pipeline.stt_worker.audio_rescue.rescue_health_snapshot',
                create=True,return_value={'available_for_next_recording':False,'used_bytes':2147480966}):
            alerts=check_operational_alerts({})
        self.assertEqual(alerts[0]['key'],'audio_rescue_capacity')
        self.assertEqual(alerts[0]['next_action'],'reclaim_closed_audio')


class EarlyReturnOutcomeTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_form_with_rejected_handoff_keeps_one_typed_outcome(self):
        with tempfile.TemporaryDirectory() as tmp, patch('data_pipeline.live_runtime.runtime_root',return_value=Path(tmp)), \
                patch.dict(os.environ,{'WEBCAST_CAPTURE_RUNNER':'container'}), \
                patch('data_pipeline.application.live_watch.probe_window',return_value=('event_window',1)):
            repo=SimpleNamespace(claim_stream_probe=Mock(return_value=True),
                record_stream_probe=Mock(return_value={'accepted':True,'capture_handoff_valid':False}),
                mark_call_running=Mock(),release_stream_probe=Mock())
            worker=SimpleNamespace(probe_date_based_call=AsyncMock(return_value=(False,'FORM_AUTOMATION_FAILED required field not found')),
                discard_promotable_probe=AsyncMock(),active_capture_count=lambda:0)
            health=Mock()
            service=LiveWatchService(repo,worker,Mock(),health)
            service._discovery_enabled=lambda:False
            service._reserve_capture=lambda c,s:True
            service._capture_environment=lambda c:{}
            await service._probe_and_launch_date_stream_call(call(),{'cooldown_minutes':1,'concurrency':1})
            outcomes=[x for x in health.record_event.call_args_list if x.args[0]=='probe_result']
            self.assertEqual(len(outcomes),1)
            self.assertIn('FORM_AUTOMATION_FAILED',outcomes[0].kwargs['error'])
            self.assertFalse(outcomes[0].kwargs['audio_ready'])
            self.assertTrue(outcomes[0].kwargs['attempt_id'])
            skipped=[x for x in health.record_event.call_args_list if x.args[0]=='capture_skipped']
            self.assertEqual(skipped[0].kwargs['error'],outcomes[0].kwargs['error'])
            repo.mark_call_running.assert_not_called()


if __name__=='__main__':
    unittest.main()
