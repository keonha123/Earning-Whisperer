"""Cross-stage recovery invariants, without external websites or production DB."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from data_pipeline import live_runtime
from data_pipeline.stt_worker.manager import STTWorkerManager, WebcastProbeResult


class ManagerIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root_patch = patch.object(live_runtime, 'runtime_root', return_value=self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.env_patch = patch.dict(os.environ, {
            'WEBCAST_CAPTURE_RUNNER': 'container', 'DATE_STREAM_DISCOVERY_HEADED': 'false',
            'DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS': '0',
            'DATE_STREAM_DISCOVERY_TIMEOUT_SECONDS': '5',
            'DATE_STREAM_DISCOVERY_TOTAL_TIMEOUT_SECONDS': '10',
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.call = {'id': 568, 'ticker': 'AZO', 'schedule_revision': 3,
                     'earning_at': '2026-09-22', '_capture_session_id': 'AZO-test-session',
                     'ir_url': 'https://issuer.example/events',
                     'event_url': 'https://issuer.example/events/q4'}

    def test_evidence_is_attempt_scoped_but_waiting_room_login_is_reused(self):
        call1, call2 = dict(self.call), dict(self.call)
        live_runtime.prepare_attempt(call1)
        live_runtime.prepare_attempt(call2)
        first = STTWorkerManager._probe_runtime_environment(call1, {})
        second = STTWorkerManager._probe_runtime_environment(call2, {})
        self.assertNotEqual(first['WEBCAST_PROGRESS_DIR'], second['WEBCAST_PROGRESS_DIR'])
        self.assertNotEqual(first['WEBCAST_CAPTURE_LOG_FILE'], second['WEBCAST_CAPTURE_LOG_FILE'])
        self.assertEqual(first['WEBCAST_STORAGE_STATE'], second['WEBCAST_STORAGE_STATE'])
        call2['schedule_revision'] += 1
        changed = STTWorkerManager._probe_runtime_environment(call2, {})
        self.assertNotEqual(first['WEBCAST_STORAGE_STATE'], changed['WEBCAST_STORAGE_STATE'])

    async def test_timeout_keeps_partial_evidence_and_tries_official_fallback(self):
        manager = STTWorkerManager()
        executable = asyncio.create_subprocess_exec
        calls = []
        target = 'https://provider.example/event-54424'
        proof = {'verified': True, 'call_ticker': 'AZO', 'target_date': '2026-09-22',
                 'source_url': self.call['ir_url'], 'target_url': target,
                 'evidence': 'dated same-event container', 'observed_at': datetime.now(timezone.utc).isoformat()}
        payload = json.dumps({'target_identity_verified': True, 'discovered_url': target,
                              'event_identity': proof})

        async def spawn(*command, **options):
            calls.append((command, options['env']))
            program = ("import time; print('candidate_inventory before timeout', flush=True); time.sleep(15)"
                       if len(calls) == 1 else 'print(' + repr('WEBCAST_DISCOVERY_RESULT=' + payload) + ')')
            return await executable(sys.executable, '-c', program, **options)

        with patch('data_pipeline.stt_worker.manager.asyncio.create_subprocess_exec', side_effect=spawn):
            result = await manager.discover_date_based_call(self.call)
        self.assertTrue(result['target_identity_verified'])
        self.assertEqual(calls[0][0][-3], self.call['event_url'])
        self.assertEqual(calls[1][0][-3], self.call['ir_url'])
        self.assertEqual(calls[0][1]['WEBCAST_ALLOW_REGISTRATION_SUBMISSION'], 'false')
        evidence = (Path(self.call['_live_progress_dir']) / 'events.jsonl').read_text()
        self.assertIn('candidate_inventory before timeout', evidence)
        self.assertIn('DISCOVERY_TIMEOUT', evidence)
        self.assertIn(target, evidence)

    async def test_verified_player_failure_is_not_bad_candidate_evidence(self):
        manager = STTWorkerManager()
        live_runtime.prepare_attempt(self.call)
        seen = []
        target = 'https://provider.example/current'

        async def probe(call, *, capture_env, timeout_seconds):
            seen.append(dict(capture_env))
            return WebcastProbeResult(False, 'PLAYBACK_READY_TIMEOUT',
                                      f'webcast target opened: {target}\n', 1,
                                      {'WEBCAST_LIVE_ENTRYPOINT_VERIFIED': 'true'})
        with patch.object(manager, 'probe_webcast_url_detailed', side_effect=probe):
            ready, _ = await manager.probe_date_based_call(self.call, capture_env={})
        self.assertFalse(ready)
        self.assertEqual(live_runtime.remembered(self.call, {'identity_mismatch'}), {})
        self.assertTrue(all(target not in item['WEBCAST_LIVE_EXCLUDED_URLS'] for item in seen))

    async def test_fair_route_budget_preserves_alternate_and_verified_waiting(self):
        manager = STTWorkerManager()
        seen = []

        async def probe(call, *, capture_env, timeout_seconds):
            seen.append((call['ir_url'], timeout_seconds))
            if len(seen) == 1:
                return WebcastProbeResult(False, 'no candidate', '', 1)
            return WebcastProbeResult(False, 'NOT_LIVE_YET same event waiting', '', 0,
                                      {'WEBCAST_LIVE_ENTRYPOINT_VERIFIED': 'true'})
        with patch.object(manager, 'probe_webcast_url_detailed', side_effect=probe):
            ready, error = await manager.probe_date_based_call(self.call, capture_env={
                'DATE_STREAM_CALL_PROBE_TIMEOUT_SECONDS': '90'})
        self.assertFalse(ready)
        self.assertIn('NOT_LIVE_YET', error)
        self.assertEqual(len(seen), 2)
        self.assertLessEqual(seen[0][1], 45)
        self.assertGreater(seen[1][1], seen[0][1])

    async def test_persisted_access_cooldown_is_reported_after_manager_restart(self):
        live_runtime.prepare_attempt(self.call)
        for url in (self.call['event_url'], self.call['ir_url']):
            live_runtime.remember(self.call, url, 'access_blocked', ttl_seconds=360)
        manager = STTWorkerManager()
        with patch.object(manager, 'probe_webcast_url_detailed', new_callable=AsyncMock) as probe:
            ready, error = await manager.probe_date_based_call(self.call, capture_env={})
        self.assertFalse(ready)
        self.assertRegex(error, r'retry_after_seconds=3[56]\d')
        probe.assert_not_awaited()

    async def test_confirmed_auth_barrier_is_not_overwritten_by_candidate_note(self):
        manager = STTWorkerManager()
        live_runtime.prepare_attempt(self.call)
        result = WebcastProbeResult(False, 'AUTH_REQUIRED email verification',
            f"webcast target opened: {self.call['event_url']}\n", 1,
            {'WEBCAST_LIVE_ENTRYPOINT_VERIFIED': 'true'})
        with patch.object(manager, 'probe_webcast_url_detailed', return_value=result):
            await manager.probe_date_based_call(self.call, capture_env={})
        memory = live_runtime.remembered(self.call, {'auth_required'})[self.call['event_url']]
        self.assertGreater(memory['expires_at'] - memory['updated_at'], 3600)

    def test_stale_process_and_growing_backlog_are_visible_without_text_heuristic(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=70)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        alerts = STTWorkerManager._progress_alerts({
            'stt': {'status': 'ready', 'timestamp_utc': old, 'backlog_seconds': 180},
            'playback': {'status': 'clock_stalled', 'warning': True, 'event': 'player_observation',
                         'timestamp_utc': now},
        }, 90)
        self.assertIn(('stt', 'PROGRESS_HEARTBEAT_STALE'), [(s, c) for s, c, _ in alerts])
        self.assertIn(('stt', 'STT_AUDIO_BACKLOG'), [(s, c) for s, c, _ in alerts])
        self.assertIn(('playback', 'player_observation'), [(s, c) for s, c, _ in alerts])
        healthy_music = {'stt': {'status': 'waiting_for_speech', 'timestamp_utc': now,
                                'last_text_age_seconds': 600, 'backlog_seconds': 4},
                         'audio': {'status': 'recording', 'timestamp_utc': now}}
        self.assertEqual(STTWorkerManager._progress_alerts(healthy_music, 600), [])


if __name__ == '__main__':
    unittest.main()
