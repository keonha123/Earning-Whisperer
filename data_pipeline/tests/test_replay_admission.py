"""Replay denial must bind the current route and leave waiting rooms usable."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from data_pipeline import live_runtime
from data_pipeline.stt_worker.manager import STTWorkerManager, WebcastProbeResult
from data_pipeline.storage.policies import capture_retry_policy, stream_probe_retry_policy


class ReplayAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.progress=self.root/'progress'; self.progress.mkdir()
        self.page=self.root/'active-url'
        self.url='https://events.q4inc.com/attendee/123456789'
        self.page.write_text(self.url+'/guest')
        self.call={'id':1,'ticker':'TEST','schedule_revision':3,
                   '_live_attempt_id':'abc123','_capture_session_id':'session',
                   '_live_progress_dir':str(self.progress),'webcast_date':'2026-10-01',
                   'ir_url':self.url,'webcast_url':self.url}
        self.env={'WEBCAST_ACTIVE_PLAYER_URL_FILE':str(self.page),
                  'WEBCAST_LIVE_ENTRYPOINT_VERIFIED':'true'}
        self.manager=STTWorkerManager()
        for p in (patch.object(live_runtime,'runtime_root',return_value=self.root),
                  patch.dict(os.environ,{'DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS':'0'},clear=True)):
            p.start(); self.addCleanup(p.stop)

    def source(self, **changes):
        value={'stage':'capture_source','version':2,'call_id':1,'ticker':'TEST','schedule_revision':3,
               'attempt_id':'abc123','capture_session_id':'session',
               'timestamp_utc':datetime.now(timezone.utc).isoformat(),
               'target_identity_verified':True,'replay_verified':True,
               'source_phase':'ended_replay_verified','capture_action':'reject_replay_route',
               'source_target_url':self.url,'source_page_url':self.url+'/guest',
               'replay_reason':'bound_recording_with_event_status',
               'player_sources':[{'media_source_fingerprint':'known-recording'}]}
        value.update(changes)
        (self.progress/'capture_source.json').write_text(json.dumps(value))
        return value

    def test_only_fresh_bound_current_player_recording_can_reject(self):
        self.source()
        self.assertTrue(self.manager._verified_replay_source(self.call,self.env))
        for changes in ({'attempt_id':'old'},{'capture_session_id':'other'},{'schedule_revision':2},
                        {'call_id':2},{'target_identity_verified':False},{'replay_verified':False},
                        {'source_phase':'waiting_for_start'},{'source_phase':'replay_candidate'},
                        {'source_phase':'live_transport_observed'},
                        {'source_target_url':self.url+'9'},
                        {'source_page_url':self.url+'9/guest'},
                        {'timestamp_utc':(datetime.now(timezone.utc)-timedelta(seconds=31)).isoformat()},
                        {'timestamp_utc':(datetime.now(timezone.utc)+timedelta(seconds=5)).isoformat()}):
            with self.subTest(changes=changes):
                self.source(**changes)
                self.assertIsNone(self.manager._verified_replay_source(self.call,self.env))
        self.source(); self.page.unlink()
        self.assertIsNone(self.manager._verified_replay_source(self.call,self.env))

    async def test_replay_is_not_promoted_and_persists_across_next_attempt(self):
        self.source()
        self.manager.probe_webcast_url_detailed=AsyncMock(return_value=WebcastProbeResult(True,None,'audio',0,self.env))
        self.manager._probe_heartbeat_loop=AsyncMock()
        self.manager.discard_promotable_probe=AsyncMock()
        ready,error=await self.manager.probe_date_based_call(self.call)
        self.assertFalse(ready); self.assertIn('VERIFIED_REPLAY_SOURCE',error)
        self.assertIn(self.url,live_runtime.remembered(self.call,{'replay_source'}))
        self.manager.probe_webcast_url_detailed.reset_mock()
        ready,_=await self.manager.probe_date_based_call({**self.call,'_live_attempt_id':'next'})
        self.assertFalse(ready)
        self.manager.probe_webcast_url_detailed.assert_not_awaited()

    async def test_waiting_music_and_unknown_source_keep_existing_audio_flow(self):
        self.manager.probe_webcast_url_detailed=AsyncMock(return_value=WebcastProbeResult(True,None,'audio',0,self.env))
        self.manager._probe_heartbeat_loop=AsyncMock()
        with patch.object(self.manager,'_write_capture_manifest',return_value=None):
            for phase in ('waiting_for_start','unconfirmed','replay_candidate','live_delivery_verified'):
                self.source(source_phase=phase,replay_verified=False,capture_action='continue_observing')
                ready,error=await self.manager.probe_date_based_call(self.call)
                self.assertTrue(ready,(phase,error))

    async def test_replay_detected_between_probe_and_launch_is_not_started(self):
        self.source(); self.manager.discard_promotable_probe=AsyncMock()
        with patch('data_pipeline.stt_worker.manager.asyncio.create_subprocess_exec',new_callable=AsyncMock) as spawn:
            with self.assertRaisesRegex(RuntimeError,'VERIFIED_REPLAY_SOURCE'):
                await self.manager.launch_date_based_audio_capture(self.call,capture_env=self.env)
            spawn.assert_not_awaited()

    async def test_held_environment_is_used_when_caller_omits_capture_env(self):
        self.source(); self.manager.discard_promotable_probe=AsyncMock()
        self.manager._promotable_probes['TEST-call-1']=SimpleNamespace(runtime_environment=self.env)
        with self.assertRaisesRegex(RuntimeError,'VERIFIED_REPLAY_SOURCE'):
            await self.manager.launch_date_based_audio_capture(self.call)

    def test_excluding_replay_evicts_discovery_cache_immediately(self):
        source=self.source()
        self.manager._discovery_cache['TEST-call-1']=(99999999,(),{'discovered_url':self.url})
        self.manager._remember_replay_source(self.call,source)
        self.assertNotIn('TEST-call-1',self.manager._discovery_cache)

    def test_redacted_public_url_requires_exact_original_fingerprint(self):
        original='https://event.webcasts.com/starthere.jsp?ei=12345&tp_key=private-value'
        self.call['webcast_url']=original; self.page.write_text(original)
        public='https://event.webcasts.com/starthere.jsp?ei=[redacted]&tp_key=[redacted]'
        self.source(source_page_url=public,source_target_url=public,
                    source_page_fingerprint=hashlib.sha256(original.encode()).hexdigest()[:24],
                    source_target_fingerprint=hashlib.sha256(original.encode()).hexdigest()[:24])
        self.assertEqual(self.manager._verified_replay_source(self.call,self.env)['source_target_url'],original)
        self.call['webcast_url']=original+'wrong'; self.page.write_text(original+'wrong')
        self.assertIsNone(self.manager._verified_replay_source(self.call,self.env))

    def test_replay_policies_request_rediscovery_without_claiming_completion(self):
        error='VERIFIED_REPLAY_SOURCE recording excluded'
        policy=stream_probe_retry_policy(error,watch_state='event_window')
        self.assertEqual(policy['reason'],'replay_source')
        self.assertTrue(policy['requires_schedule_refresh'])
        self.assertEqual(capture_retry_policy(error,attempts=1)['reason'],'replay_source')
