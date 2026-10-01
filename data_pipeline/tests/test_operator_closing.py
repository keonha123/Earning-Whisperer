"""Explicit call endings must not collapse into a silence heuristic."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from data_pipeline.live_end import (TranscriptEndObserver, explicit_operator_close,
                                   load_bound_target_proof, publish_operator_end,
                                   write_bound_target_proof)

CLOSE = "Thank you. This brings us to the end of today's meeting. We appreciate your time and participation. You may now disconnect."


class ClosingTextTest(unittest.TestCase):
    def prepared(self):
        observer=TranscriptEndObserver()
        for i in range(12):
            observer.observe('Our revenue and operating margin improved this quarter.', audio_seconds=20*(i+1), backlog_seconds=0)
        return observer

    def test_actual_payx_requires_settled_processed_audio(self):
        observer=self.prepared()
        self.assertIsNone(observer.observe(CLOSE,audio_seconds=260,backlog_seconds=0))
        self.assertIsNone(observer.observe('',audio_seconds=280,backlog_seconds=0))
        self.assertIsNone(observer.observe('BORNAN BOR.',audio_seconds=300,backlog_seconds=0))
        self.assertEqual(observer.observe('',audio_seconds=320,backlog_seconds=0)['post_close_audio_seconds'],60)

    def test_silence_thanks_qa_and_future_quotation_cannot_end(self):
        for text in ('Thank you for joining. Have a good day.',
                     'This concludes the question and answer session. You may now disconnect.',
                     "If this concludes today's meeting, you may now disconnect.",
                     "An operator said this concludes today's call. You may now disconnect.",
                     'This concludes our meeting about product design.', ''):
            self.assertFalse(explicit_operator_close(text),text)
            observer=self.prepared()
            observer.observe(text,audio_seconds=260,backlog_seconds=0)
            self.assertIsNone(observer.observe('',audio_seconds=900,backlog_seconds=0))

    def test_continuing_substantive_speech_cancels_candidate(self):
        observer=self.prepared();observer.observe(CLOSE,audio_seconds=260,backlog_seconds=0)
        observer.observe('We have another question from the analyst.',audio_seconds=280,backlog_seconds=0)
        self.assertIsNone(observer.candidate)
        self.assertIsNone(observer.observe('',audio_seconds=1000,backlog_seconds=0))

    def test_short_continuation_is_speech_and_cancels(self):
        for text in ('Please hold.', 'Another question?', "Don't disconnect.", 'Please wait.', 'Yes.'):
            observer=self.prepared();observer.observe(CLOSE,audio_seconds=260,backlog_seconds=0)
            observer.observe(text,audio_seconds=280,backlog_seconds=0)
            self.assertIsNone(observer.candidate,text)
            self.assertIsNone(observer.observe('',audio_seconds=900,backlog_seconds=0))

    def test_backlog_or_one_window_cannot_confirm(self):
        observer=self.prepared();observer.observe(CLOSE,audio_seconds=260,backlog_seconds=0)
        self.assertIsNone(observer.observe('',audio_seconds=320,backlog_seconds=0))
        self.assertIsNone(observer.observe('',audio_seconds=340,backlog_seconds=90))
        self.assertIsNotNone(observer.observe('',audio_seconds=360,backlog_seconds=0))

    def test_short_preamble_or_early_hallucination_cannot_end(self):
        observer=TranscriptEndObserver()
        for t in (20,40,60):self.assertIsNone(observer.observe(CLOSE,audio_seconds=t,backlog_seconds=0))
        self.assertIsNone(observer.candidate)

    def test_split_operator_closing_is_allowed_but_old_quote_is_not(self):
        observer=self.prepared()
        observer.observe("This concludes today's conference call.",audio_seconds=260,backlog_seconds=0)
        observer.observe('Thank you for participating. You may now disconnect.',audio_seconds=280,backlog_seconds=0)
        self.assertIsNotNone(observer.candidate)
        stale=self.prepared()
        stale.observe("This concludes today's conference call.",audio_seconds=260,backlog_seconds=0)
        stale.observe('You may now disconnect.',audio_seconds=400,backlog_seconds=0)
        self.assertIsNone(stale.candidate)


class BoundProofTest(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.ready=root/'ready';self.active=root/'active';self.end=root/'end.json'
        self.start=time.time()-2
        self.env=patch.dict(os.environ,{'CALL_ID':'call-session','STT_CAPTURE_SESSION_ID':'capture',
            'TICKER':'PAYX','WEBCAST_TARGET_DATE':'2026-09-23',
            'WEBCAST_LIVE_RUN_ID':'this-run','WEBCAST_LIVE_RUN_STARTED_AT':str(self.start),
            'WEBCAST_TARGET_IDENTITY_READY_FILE':str(self.ready),
            'WEBCAST_ACTIVE_PLAYER_URL_FILE':str(self.active),
            'WEBCAST_LIVE_TERMINATION_FILE':str(self.end)})
        self.env.start();self.addCleanup(self.env.stop)
        self.config=SimpleNamespace(live_capture=True,supervised_live=True,target_identity_verified=True,
            live_run_id='this-run',target_event_date='2026-09-23',call_id='call-session',
            capture_session_id='capture',live_run_started_at=self.start,ticker='PAYX',live_termination_file=str(self.end))
        self.proof={'verified':True,'call_ticker':'PAYX','target_date':'2026-09-23',
            'target_url':'https://edge.media-server.com/mmc/p/current1',
            'observed_at':datetime.now(timezone.utc).isoformat()}
        self.active.write_text(self.proof['target_url']+'/')
        write_bound_target_proof(self.ready,self.proof)

    def test_same_run_proof_can_publish_and_is_read_by_existing_supervisor(self):
        self.assertIsNotNone(load_bound_target_proof(self.config))
        result=publish_operator_end(self.config,{'text':CLOSE,'post_close_audio_seconds':60})
        self.assertEqual(result['reason'],'event_ended')
        from data_pipeline.collectors.streams.browser.lifetime import read_current_termination
        self.assertEqual(read_current_termination(self.end)['reason'],'event_ended')

    def test_another_run_date_route_or_unverified_flag_cannot_publish(self):
        for key,value in [('live_run_id','old'),('target_event_date','2026-09-22'),
                          ('capture_session_id','old-session'),('target_identity_verified',False)]:
            config=SimpleNamespace(**{**vars(self.config),key:value})
            self.assertIsNone(publish_operator_end(config,{'text':CLOSE,'post_close_audio_seconds':60}))
        self.active.write_text('https://edge.media-server.com/mmc/p/different1/')
        self.assertIsNone(load_bound_target_proof(self.config))
        self.assertFalse(self.end.exists())

    def test_plain_readiness_flag_is_not_structured_proof(self):
        Path(str(self.ready)+'.proof.json').unlink()
        self.ready.write_text('verified')
        self.assertIsNone(load_bound_target_proof(self.config))

    def test_browser_verified_redirect_url_is_bound_without_broad_host_equivalence(self):
        self.active.write_text('https://different-provider.test/validated-player')
        self.assertIsNone(load_bound_target_proof(self.config))
        write_bound_target_proof(self.ready,self.proof,
                                 validated_url='https://different-provider.test/validated-player')
        self.assertIsNotNone(load_bound_target_proof(self.config))
        self.active.write_text('https://different-provider.test/unrelated-player')
        self.assertIsNone(load_bound_target_proof(self.config))

    def test_malformed_companion_is_unverified_without_exception(self):
        for value in ([], None, {'proof': []}, {'proof': 'invalid'}):
            Path(str(self.ready)+'.proof.json').write_text(json.dumps(value))
            self.assertIsNone(load_bound_target_proof(self.config))
