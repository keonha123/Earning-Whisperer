"""Live completion uses actual SQL and must reject timer/disconnect success rows."""
import asyncio
from contextlib import ExitStack
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event, text
from data_pipeline.storage import live_calls
from data_pipeline.storage.policies import capture_retry_policy
from data_pipeline.stt_worker.manager import STTWorkerManager


class LiveCompletionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        @event.listens_for(self.engine, 'connect')
        def functions(dbapi, _):
            dbapi.create_function('CHAR_LENGTH', 1, lambda s: len(s) if s is not None else None)
        @event.listens_for(self.engine, 'before_cursor_execute', retval=True)
        def sql_dialect(conn, cursor, statement, parameters, context, many):
            # SQLite cannot exercise MySQL row locks; it can execute the same
            # completion predicates and updates without mocking their result.
            return re.sub(r'\bFOR UPDATE\b', '', statement), parameters
        for name in ('ensure_schedule_time_schema','ensure_transcript_archive_schema'):
            self.stack.enter_context(patch.object(live_calls.schema, name))
        self.stack.enter_context(patch.object(live_calls.connection, 'engine', self.engine))
        self.stack.enter_context(patch.object(live_calls, '_pipeline_worker_id', return_value='owner'))
        self.stack.enter_context(patch.dict(os.environ, {'STT_COMPLETION_MIN_SEGMENTS':'2','STT_COMPLETION_MIN_CHARACTERS':'80'}))
        with self.engine.begin() as c:
            c.execute(text('''CREATE TABLE calls (
                id INTEGER PRIMARY KEY, status TEXT, capture_lease_owner TEXT,
                capture_session_id TEXT, capture_lease_until TEXT, capture_started_at TEXT,
                capture_heartbeat_at TEXT, capture_previous_status TEXT,
                capture_retry_not_before TEXT, capture_last_error TEXT, stream_probe_status TEXT)'''))
            c.execute(text('''CREATE TABLE transcript_segments (
                call_id TEXT, text_chunk TEXT, is_session_end BOOLEAN,
                session_success_eligible BOOLEAN, target_identity_verified BOOLEAN, session_end_reason TEXT)'''))
            c.execute(text("INSERT INTO calls (id,status,capture_lease_owner,capture_session_id) VALUES (1,'running','owner','session')"))

    def seed(self, reason, *, success=True, identity=True):
        with self.engine.begin() as c:
            c.execute(text('DELETE FROM transcript_segments'))
            c.execute(text("UPDATE calls SET status='running',capture_lease_owner='owner'"))
            c.execute(text("INSERT INTO transcript_segments VALUES ('session',:body,0,0,0,NULL)"), {'body':'Actual earnings discussion. '*5})
            c.execute(text("INSERT INTO transcript_segments VALUES ('session',:body,1,:success,:identity,:reason)"), {'body':'Last recorded speech. '*5,'reason':reason,'success':success,'identity':identity})

    def state(self):
        with self.engine.connect() as c:
            return c.execute(text('SELECT status,capture_lease_owner FROM calls WHERE id=1')).one()

    def test_limits_idle_eof_and_legacy_success_do_not_complete(self):
        for reason in ('bounded_capture_complete','speech_idle_timeout','input_ended',
                       'live_session_guard','live_source_lost','legacy_terminal_marker',None):
            with self.subTest(reason=reason):
                self.seed(reason)
                result=live_calls.complete_call_capture_from_transcript(1,'session')
                self.assertFalse(result['completed'])
                self.assertEqual(result['valid_end_count'],0)
                self.assertEqual(tuple(self.state()),('running','owner'))
                self.assertEqual(live_calls.complete_recovered_call_captures_from_transcripts(['session']),0)
                self.assertEqual(tuple(self.state()),('running','owner'))

    def test_confirmed_end_finishes_and_releases_lease(self):
        self.seed('event_ended')
        self.assertTrue(live_calls.complete_call_capture_from_transcript(1,'session')['completed'])
        self.assertEqual(tuple(self.state()),('completed',None))

    def test_spooled_confirmed_end_can_recover_but_requires_identity_and_success(self):
        for success,identity in ((False,True),(True,False),(False,False),(True,True)):
            with self.subTest(success=success,identity=identity):
                self.seed('event_ended',success=success,identity=identity)
                self.assertEqual(live_calls.complete_recovered_call_captures_from_transcripts(['session']),int(success and identity))

    def test_old_session_or_split_evidence_cannot_complete_current_capture(self):
        self.seed('event_ended',success=False)
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO transcript_segments VALUES ('session','text',1,1,1,'bounded_capture_complete')"))
            c.execute(text("INSERT INTO transcript_segments VALUES ('old-session','text',1,1,1,'event_ended')"))
        self.assertFalse(live_calls.complete_call_capture_from_transcript(1,'session')['completed'])
        self.assertEqual(live_calls.complete_recovered_call_captures_from_transcripts(['old-session','session']),0)


class LiveIncompleteRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_guard_exit_requeues_instead_of_completing(self):
        for code in (76,77,78):
            with self.subTest(code=code), patch('data_pipeline.database.requeue_failed_call_capture',return_value=True) as retry, patch('data_pipeline.database.complete_call_capture_from_transcript') as complete:
                manager=STTWorkerManager()
                process=SimpleNamespace(wait=AsyncMock(return_value=code))
                await manager._watch_process({'id':1,'ticker':'LEN','_capture_session_id':'session'},'LEN-call-1',process)
                complete.assert_not_called()
                self.assertIn('LIVE_CAPTURE_INCOMPLETE',retry.call_args.kwargs['error'])
                self.assertEqual(retry.call_args.kwargs['capture_session_id'],'session')

    def test_continuation_delay_does_not_grow_with_attempts(self):
        with patch.dict(os.environ,{},clear=True):
            for attempts in (1,2,10):
                policy=capture_retry_policy('LIVE_CAPTURE_INCOMPLETE reason=live_source_lost',attempts=attempts)
                self.assertEqual(policy['retry_delay_minutes'],1)
                self.assertEqual(policy['max_attempts'],0)
            protected=capture_retry_policy('LIVE_CAPTURE_INCOMPLETE CAPTCHA',attempts=2)
            self.assertEqual(protected['reason'],'auth_required')

    def test_final_lifecycle_reason_is_retained_over_registration_history(self):
        with TemporaryDirectory() as directory:
            log=Path(directory)/'capture.log'
            log.write_text('registration form detected\nPLAYBACK_READY\nSTT_LIVE_INCOMPLETE reason=live_session_guard\n')
            detail=STTWorkerManager()._capture_failure_detail({'_capture_log_path':str(log)})
            self.assertIn('live_session_guard',detail)
            self.assertNotIn('registration',detail)

    def test_terminal_files_are_isolated_between_events(self):
        manager=STTWorkerManager()
        with patch.dict(os.environ,{},clear=True):
            first=manager.build_isolated_capture_environment({'id':1,'ticker':'LEN','ir_url':'https://issuer.invalid/a'})
            second=manager.build_isolated_capture_environment({'id':2,'ticker':'LEN','ir_url':'https://issuer.invalid/b'})
        self.assertNotEqual(first['WEBCAST_LIVE_TERMINATION_FILE'],second['WEBCAST_LIVE_TERMINATION_FILE'])
