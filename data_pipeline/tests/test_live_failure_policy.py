import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from data_pipeline.failure_reasons import classify_live_failure, classify_stream_failure
from data_pipeline.operations import classify_failure
from data_pipeline.storage.policies import capture_retry_policy, stream_probe_retry_policy


class TypedLiveFailurePolicyTest(unittest.TestCase):
    def test_actual_error_strings_keep_stage_and_code(self):
        cases=[('LIVE_TARGET_UNCONFIRMED no dated target candidate','discovery','LIVE_TARGET_UNCONFIRMED','candidate_unavailable'),
               ('PLAYBACK_READY_TIMED_OUT timeout=180s','playback','PLAYBACK_READY_TIMED_OUT','playback_failed'),
               ('REGISTRATION_REQUIRED registration submission did not transition','registration','FORM_AUTOMATION_FAILED','form_automation_failed'),
               ('REGISTRATION_REQUIRED registration field unavailable: first_name','registration','FORM_AUTOMATION_FAILED','form_automation_failed'),
               ('AUDIO_NOT_DETECTED within=90s','audio','AUDIO_NOT_DETECTED','audio_failed')]
        for error,stage,code,reason in cases:
            with self.subTest(error=error):
                typed=classify_live_failure(error)
                self.assertEqual((typed['stage'],typed['error_code'],typed['reason']),(stage,code,reason))
                legacy=classify_failure(error)
                self.assertEqual(legacy['stage'],stage)
                self.assertEqual(legacy['error_code'],code)
                self.assertEqual(classify_stream_failure(error),reason)

    def test_near_call_rechecks_other_routes_without_removing_barriers(self):
        with patch.dict(os.environ,{},clear=True):
            for error,far in [('target date mismatch',60),('HTTP 403 forbidden',360),('HTTP 429 rate limit',360)]:
                self.assertEqual(stream_probe_retry_policy(error,watch_state='event_window')['retry_delay_minutes'],1)
                self.assertEqual(stream_probe_retry_policy(error)['retry_delay_minutes'],far)
            for error in ['CAPTCHA human verification','REGISTRATION_REQUIRED registration submission is disabled','REGISTRATION_APPROVAL_REQUIRED approval manifest is missing','AUTH_REQUIRED email login link']:
                self.assertEqual(classify_stream_failure(error),'auth_required')
                self.assertEqual(capture_retry_policy(error,attempts=1)['max_attempts'],1)
                self.assertEqual(stream_probe_retry_policy(error)['retry_delay_minutes'],720)
            self.assertEqual(classify_stream_failure('LIVE_CAPTURE_INCOMPLETE CAPTCHA'),'auth_required')
            self.assertEqual(classify_stream_failure('FORM_AUTOMATION_FAILED HTTP 403'),'access_blocked')

    def test_automatable_form_capture_retries_are_short_and_bounded(self):
        with patch.dict(os.environ,{},clear=True):
            error='REGISTRATION_REQUIRED registration submit control not found'
            for attempt in (1,2,20):
                policy=capture_retry_policy(error,attempts=attempt)
                self.assertEqual((policy['reason'],policy['retry_delay_minutes'],policy['max_attempts']),('form_automation_failed',1,3))
            self.assertEqual(stream_probe_retry_policy(error,watch_state='date_only')['retry_delay_minutes'],1)

    def test_live_continuation_does_not_backoff_by_attempt(self):
        with patch.dict(os.environ,{},clear=True):
            for code in (70,71,74,76,77,78):
                for attempt in (1,4,20):
                    policy=capture_retry_policy(f'LIVE_CAPTURE_INCOMPLETE exit={code}',attempts=attempt)
                    self.assertEqual((policy['retry_delay_minutes'],policy['max_attempts']),(1,0))
            self.assertEqual(capture_retry_policy('unclassified capture failure',attempts=4)['retry_delay_minutes'],24)

    def test_future_start_wait_is_preserved(self):
        start=datetime.now(timezone.utc)+timedelta(minutes=31)
        policy=stream_probe_retry_policy(f'NOT_LIVE_YET scheduled event time is in the future: {start.isoformat()}',watch_state='event_window')
        self.assertEqual(policy['reason'],'scheduled_start_wait')
        self.assertGreaterEqual(policy['retry_delay_minutes'],25)

    def test_typed_producer_details_are_preserved(self):
        result=classify_failure({'stage':'playback','error_code':'PLAYER_JS_ERROR','message':'timeout'})
        self.assertEqual((result['stage'],result['error_code']),('playback','PLAYER_JS_ERROR'))

    def test_common_codes_roundtrip_without_losing_retry_semantics(self):
        for error in ('target date mismatch', 'PCM source lost', 'PulseAudio server did not start',
                      'REGISTRATION_REQUIRED registration submission did not transition',
                      'LIVE_TARGET_UNCONFIRMED no dated target candidate'):
            original=classify_live_failure(error)
            typed=classify_live_failure({'stage':original['stage'],'error_code':original['error_code']})
            self.assertEqual(typed['reason'],original['reason'])


if __name__ == '__main__':
    unittest.main()
