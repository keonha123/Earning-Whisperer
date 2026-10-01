"""Exercise real queue, transcription loop, proof publication and tail drain."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from data_pipeline.tests.test_live_capture_lifecycle import Clock, Producer, CaptureEmitter, args
from data_pipeline.tests.test_operator_closing import CLOSE
from data_pipeline.tests.test_operator_closing_recent_calls import MU_CLOSE, JBL_CLOSE, JBL_FOLLOWUP
from data_pipeline.stt_worker import take
from data_pipeline.stt_worker.config import config_from_args
from data_pipeline.live_end import write_bound_target_proof


class OperatorClosingLifecycleTest(unittest.TestCase):
    def capture(self, *, resumed=None, corrupt_proof=False, close=CLOSE, followups=None, count=18):
        with TemporaryDirectory() as directory:
            root=Path(directory);ready=root/'ready';active=root/'active';marker=root/'end'
            clock=Clock();producer=Producer([struct.pack('<h',i)*320000 for i in range(1,count+1)])
            emitter=CaptureEmitter();seen=[]
            def transcribe(audio,**kwargs):
                i=int(round(float(audio[0])*32768));seen.append(i);clock.now+=20
                text=(f'Unique statement number {i} includes the current quarter business forecast.' if i<=12
                      else close if i==13 else (followups or {})[i] if i in (followups or {})
                      else resumed if i==15 and resumed
                      else 'BORNAN BOR.' if i==16 else '')
                return ([SimpleNamespace(text=text)] if text else []),None
            env={'WEBCAST_LIFECYCLE':'live','WEBCAST_SUPERVISED_LIVE':'true',
                 'WEBCAST_LIVE_TERMINATION_FILE':str(marker),'WEBCAST_LIVE_RUN_ID':'current-run',
                 'WEBCAST_LIVE_RUN_STARTED_AT':str(time.time()-2),'CALL_ID':'TEST-current-call',
                 'STT_CAPTURE_SESSION_ID':'capture','STT_TARGET_IDENTITY_VERIFIED':'true',
                 'WEBCAST_TARGET_DATE':'2026-09-18','TICKER':'TEST',
                 'WEBCAST_TARGET_IDENTITY_READY_FILE':str(ready),'WEBCAST_ACTIVE_PLAYER_URL_FILE':str(active)}
            with patch.dict(os.environ,env,clear=True):
                config=replace(config_from_args(args()),read_bytes=640000,overlap_bytes=0)
                target='https://edge.media-server.com/mmc/p/fixture1'
                active.write_text(target+'/')
                proof={'verified':True,'call_ticker':'TEST','target_date':'2026-09-18','target_url':target,
                       'observed_at':datetime.now(timezone.utc).isoformat()}
                write_bound_target_proof(ready,proof)
                if corrupt_proof:
                    p=Path(str(ready)+'.proof.json');v=json.loads(p.read_text());v['run_id']='old-run';p.write_text(json.dumps(v))
                with patch.object(take,'time',SimpleNamespace(monotonic=clock.monotonic,time=time.time)),\
                     patch.object(take,'load_whisper_model',return_value=SimpleNamespace(transcribe=transcribe)),\
                     patch.object(take,'run_audio_preflight',return_value=None),\
                     patch.object(take.subprocess,'Popen',return_value=producer),\
                     patch.object(take,'_read_available_audio',side_effect=producer.read),\
                     patch.object(take,'TranscriptEmitter',return_value=emitter):
                    code=take.run_transcription(config)
                return code,emitter.terminal,seen,marker.exists(),emitter.texts

    def test_explicit_close_after_settle_drains_and_archives_success(self):
        code,terminal,seen,marker,texts=self.capture()
        self.assertEqual(code,0)
        self.assertTrue(marker)
        self.assertEqual(terminal['termination_reason'],'event_ended')
        self.assertTrue(terminal['success_eligible'])
        self.assertEqual(seen,list(range(1,19)))
        self.assertTrue(any('now disconnect' in t for t in texts))

    def test_real_short_followup_keeps_session_incomplete(self):
        code,terminal,seen,marker,_=self.capture(resumed='Please hold.')
        self.assertEqual(code,take.STT_EXIT_LIVE_INCOMPLETE)
        self.assertFalse(marker)
        self.assertFalse(terminal['success_eligible'])

    def test_closing_without_current_run_proof_cannot_complete(self):
        code,terminal,seen,marker,_=self.capture(corrupt_proof=True)
        self.assertEqual(code,take.STT_EXIT_LIVE_INCOMPLETE)
        self.assertFalse(marker)
        self.assertFalse(terminal['success_eligible'])

    def test_actual_mu_joint_closing_completes_after_all_tail_audio_is_processed(self):
        code,terminal,seen,marker,texts=self.capture(close=MU_CLOSE, count=24)
        self.assertEqual(code,0)
        self.assertTrue(marker)
        self.assertEqual(terminal['termination_reason'],'event_ended')
        self.assertTrue(terminal['success_eligible'])
        self.assertEqual(seen,list(range(1,25)))
        self.assertIn(MU_CLOSE,texts)

    def test_actual_jbl_closing_followups_extend_then_complete_and_drain(self):
        with patch.object(take,'emit_live_event') as events:
            code,terminal,seen,marker,texts=self.capture(close=JBL_CLOSE,
                followups={14:JBL_FOLLOWUP,15:'Thank you.'},count=24)
        self.assertEqual(code,0)
        self.assertTrue(marker)
        self.assertTrue(terminal['success_eligible'])
        self.assertEqual(seen,list(range(1,25)))
        extended=[c for c in events.call_args_list if c.args[:2]==('stt','operator_closing_candidate')
                  and c.kwargs.get('status')=='extended']
        self.assertEqual(len(extended),2)

    def test_financial_speech_after_jbl_followup_prevents_normal_completion(self):
        code,terminal,seen,marker,_=self.capture(close=JBL_CLOSE,
            followups={14:JBL_FOLLOWUP,15:'Thank you.',16:'Our revenue outlook will increase next quarter.'},count=24)
        self.assertEqual(code,take.STT_EXIT_LIVE_INCOMPLETE)
        self.assertFalse(marker)
        self.assertFalse(terminal['success_eligible'])
        self.assertEqual(seen,list(range(1,25)))

    def test_duplicate_archive_text_is_not_quiet_audio_for_closing(self):
        code,terminal,seen,marker,texts=self.capture(close=MU_CLOSE,
            followups={i:'Thank you.' for i in range(14,25)},count=24)
        # Archiving may omit repeated text; the observed audio windows still
        # contain speech and have no following 60-second quiet confirmation.
        self.assertEqual(texts.count('Thank you.'),1)
        self.assertEqual(code,take.STT_EXIT_LIVE_INCOMPLETE)
        self.assertFalse(marker)
        self.assertFalse(terminal['success_eligible'])
        self.assertEqual(seen,list(range(1,25)))
