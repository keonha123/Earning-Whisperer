"""The watcher commits browser clocks before playback and rejects stale handoff."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from data_pipeline.application.live_watch import LiveWatchService
from data_pipeline.collectors.schedules.browser_observation import observe_browser_time
from data_pipeline.tests.test_browser_schedule_observation import fixture, TEXT


class BrowserScheduleWatchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'WEBCAST_RUNTIME_ROOT': self.temp.name,
            'OPERATIONS_LOG_DIR': self.temp.name, 'DATE_STREAM_WATCH_CONCURRENCY': '1',
            'DATE_STREAM_CAPTURE_CONCURRENCY': '1', 'DATE_STREAM_AUTO_CAPTURE_ENABLED': 'true'})
        env.start(); self.addCleanup(env.stop)
        self.agent, self.call = fixture()
        self.call['status'] = 'upcoming'
        self.observation = observe_browser_time(self.agent, TEXT)
        self.repo = SimpleNamespace(claim_stream_probe=Mock(return_value=True),
            record_stream_probe=Mock(return_value={'accepted': True, 'schedule_applied': True,
                'schedule_changed': True, 'capture_handoff_valid': False,
                'schedule_context': {'schedule_revision': 3, 'scheduled_at_utc': '2026-09-23 14:30:00'}}),
            mark_call_running=Mock(return_value=True), requeue_failed_call_capture=Mock())
        self.worker = SimpleNamespace(discover_date_based_call=AsyncMock(),
            probe_date_based_call=AsyncMock(return_value=(True, None)),
            discard_promotable_probe=AsyncMock(), launch_date_based_audio_capture=AsyncMock(),
            active_capture_count=lambda: 0, occupied_capture_keys=lambda: set())
        self.service = LiveWatchService(self.repo, self.worker, SimpleNamespace(), Mock())
        self.service._discovery_enabled = lambda: True
        self.service._capture_environment = lambda call: {}
        self.service._reserve_capture = lambda call, settings: True

    async def run_watch(self):
        await self.service._probe_and_launch_date_stream_call(self.call, self.service._date_stream_settings())

    async def test_new_discovery_clock_is_saved_before_registration_or_audio(self):
        async def discover(call):
            call['_browser_schedule_observation'] = self.observation
            return {'target_identity_verified': True, 'discovered_url': self.agent.live_target_proof['target_url'],
                    'identity_proof': self.agent.live_target_proof}
        self.worker.discover_date_based_call.side_effect = discover
        await self.run_watch()
        values = self.repo.record_stream_probe.call_args.kwargs['schedule_observation']
        self.assertEqual(str(values['scheduled_at_utc']), '2026-09-23 14:30:00')
        self.assertEqual(self.repo.record_stream_probe.call_args.kwargs['expected_schedule_revision'], 2)
        self.worker.probe_date_based_call.assert_not_awaited()
        self.repo.mark_call_running.assert_not_called()

    async def heavy_observation(self):
        self.worker.discover_date_based_call.return_value = {'retry_state': 'browser_action_required'}
        async def probe(call, **kwargs):
            call['_browser_schedule_observation'] = self.observation
            return True, None
        self.worker.probe_date_based_call.side_effect = probe
        await self.run_watch()

    async def test_ready_audio_against_changed_schedule_is_discarded(self):
        await self.heavy_observation()
        self.repo.mark_call_running.assert_not_called()
        self.worker.discard_promotable_probe.assert_awaited_once()

    async def test_lost_probe_owner_cannot_promote_audio(self):
        self.repo.record_stream_probe.return_value = {'accepted': False, 'capture_handoff_valid': False}
        await self.heavy_observation()
        self.repo.mark_call_running.assert_not_called()
        self.worker.discard_promotable_probe.assert_awaited_once()

    async def test_unchanged_schedule_keeps_verified_ready_browser(self):
        self.repo.record_stream_probe.return_value = {'accepted': True, 'schedule_applied': True,
            'schedule_changed': False, 'capture_handoff_valid': True}
        await self.heavy_observation()
        self.repo.mark_call_running.assert_called_once()
        self.worker.launch_date_based_audio_capture.assert_awaited_once()
        self.worker.discard_promotable_probe.assert_not_awaited()

    def test_retained_clock_conflict_has_distinct_diagnostics_without_policy_change(self):
        self.call['_browser_schedule_observation'] = self.observation
        result = {'accepted': True, 'schedule_applied': False, 'schedule_conflicted': True,
            'capture_handoff_valid': True, 'schedule_changed': False,
            'reason': 'schedule_clock_conflict',
            'clock_observations': [{'source':'issuer'}, {'source':'provider'}],
            'missing_clock_sources': ['issuer'],
            'schedule_context': {'schedule_revision': 3, 'scheduled_at_utc': None}}
        self.repo.record_stream_probe.return_value = result
        with patch('data_pipeline.application.live_watch.live_runtime.record') as runtime:
            returned = self.service._record_probe(self.call['id'], call=self.call, stream_ready=True)
        self.assertIs(returned, result)
        event = self.service.health.record_event.call_args
        self.assertEqual(event.args[0], 'browser_clock_conflict_retained')
        self.assertEqual(event.kwargs['status'], 'provisional_watch')
        self.assertEqual(event.kwargs['clock_source_count'], 2)
        self.assertEqual(event.kwargs['missing_clock_source_count'], 1)
        self.assertIsNone(event.kwargs['scheduled_at_utc'])
        self.assertEqual(runtime.call_args.args[2], 'browser_clock_conflict_retained')
        self.assertEqual(runtime.call_args.kwargs['status'], 'provisional_watch')
        self.assertFalse(runtime.call_args.kwargs['progress'])

    def test_stale_or_rejected_write_is_not_logged_as_retained_conflict(self):
        self.call['_browser_schedule_observation'] = self.observation
        # Even a conflicting flag without accepted ownership cannot claim that
        # this writer preserved anything in the database.
        self.repo.record_stream_probe.return_value = {
            'accepted': False, 'schedule_applied': False, 'schedule_conflicted': True}
        with patch('data_pipeline.application.live_watch.live_runtime.record') as runtime:
            self.service._record_probe(self.call['id'], call=self.call, stream_ready=False)
        event = self.service.health.record_event.call_args
        self.assertEqual(event.args[0], 'browser_schedule_time')
        self.assertEqual(event.kwargs['status'], 'stale_or_rejected')
        self.assertNotIn('clock_conflict_retained', event.kwargs)
        self.assertEqual(runtime.call_args.args[2], 'browser_start_rejected')
