import os
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from data_pipeline.failure_reasons import classify_stream_failure
from data_pipeline.stt_worker.manager import STTWorkerManager, WebcastProbeResult
from data_pipeline.storage.policies import stream_probe_retry_policy, capture_retry_policy
from data_pipeline.operations import classify_failure


class RetryRegression(unittest.IsolatedAsyncioTestCase):
    async def test_new_candidate_after_one_minute_reaches_browser_again(self):
        manager = STTWorkerManager()
        call = {'id': 123456, 'ticker': 'TEST', 'earning_at': '2026-09-17',
                'ir_url': 'https://example.invalid/ir'}
        error = 'no candidate\nMEDIA_FALLBACK_BLOCKED target_identity_unconfirmed'
        manager.probe_webcast_url_detailed = AsyncMock(side_effect=[
            WebcastProbeResult(False, error, error, 1),
            WebcastProbeResult(True, None, 'AUDIO_DETECTED', 0,
                               {'WEBCAST_LIVE_ENTRYPOINT_VERIFIED': 'true'}),
        ])
        manager._probe_heartbeat_loop = AsyncMock()
        with patch.dict(os.environ, {}, clear=True), patch.object(manager, '_write_capture_manifest', return_value=None):
            with patch('data_pipeline.stt_worker.manager.time', SimpleNamespace(monotonic=lambda: 1000)):
                first = await manager.probe_date_based_call(call)
            self.assertFalse(first[0])
            self.assertEqual(stream_probe_retry_policy(first[1], watch_state='event_window')['retry_delay_minutes'], 1)
            with patch('data_pipeline.stt_worker.manager.time', SimpleNamespace(monotonic=lambda: 1061)):
                second = await manager.probe_date_based_call(call)
        self.assertTrue(second[0], second[1])
        self.assertEqual(manager.probe_webcast_url_detailed.await_count, 2)
        self.assertEqual(manager._entrypoint_retry_not_before, {})

    def test_guard_is_pending_in_probe_capture_and_operations(self):
        error = 'MEDIA_FALLBACK_BLOCKED target_identity_unconfirmed'
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(classify_stream_failure(error), 'candidate_unavailable')
            self.assertEqual(stream_probe_retry_policy(error, watch_state='date_only')['reason'], 'candidate_unavailable')
            capture = capture_retry_policy(error, attempts=1)
            self.assertEqual(capture['reason'], 'candidate_unavailable')
            self.assertEqual(capture['max_attempts'], 0)
            self.assertEqual(capture['retry_delay_minutes'], 3)
            self.assertEqual(classify_failure(error)['category'], 'no_candidate')

    def test_real_blocks_are_preserved_even_alongside_internal_guard(self):
        for detail, reason in [('HTTP 403 forbidden', 'access_blocked'),
                               ('HTTP 429 rate limit', 'access_blocked'),
                               ('CAPTCHA email verification', 'auth_required')]:
            with self.subTest(detail=detail), patch.dict(os.environ, {}, clear=True):
                error = 'MEDIA_FALLBACK_BLOCKED target_identity_unconfirmed; ' + detail
                self.assertEqual(classify_stream_failure(error), reason)
                self.assertEqual(stream_probe_retry_policy(error)['reason'], reason)
                self.assertEqual(capture_retry_policy(error, attempts=1)['reason'], reason)
                manager = STTWorkerManager()
                manager._cooldown_failed_entrypoint({'id':1}, 'ir_url', 'https://example.invalid', error)
                self.assertEqual(len(manager._entrypoint_retry_not_before), 1)
