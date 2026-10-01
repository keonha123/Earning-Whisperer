"""Identity/TTL/operator-boundary tests; no live network, DB or child browser."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, text

from data_pipeline import live_runtime
from data_pipeline.stt_worker.manager import STTWorkerManager
from data_pipeline.tools.debug import live_control


class RuntimeControlBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(live_runtime, 'runtime_root', return_value=self.root).start()
        patch.dict(os.environ, {'WEBCAST_CAPTURE_RUNNER':'container'}).start()
        self.call = dict(id=568,ticker='AZO',schedule_revision=7,earning_at='2026-09-22',
                         ir_url='https://investors.example.test/events',status='running',
                         capture_session_id='session-A',_capture_session_id='session-A')
        live_runtime.prepare_attempt(self.call)

    def request(self, **changes):
        return {**live_runtime.context(self.call), 'request_id':'request-A',
                'requested_at':datetime.now(timezone.utc).isoformat(), **changes}

    def test_status_queries_archive_schema_and_only_current_session(self):
        engine=create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE transcript_segments (call_id TEXT, sequence_no INT, created_at TEXT)'))
            connection.execute(text("INSERT INTO transcript_segments VALUES ('session-A',4,'2026-09-22 14:00:00'),('old-session',999,'2026-09-21 14:00:00')"))
        output=StringIO()
        with patch.object(live_control,'engine',engine), patch.object(live_control,'fetch_call',return_value=self.call), redirect_stdout(output):
            self.assertEqual(live_control.main(['status','--call-id','568']),0)
        transcript=json.loads(output.getvalue())['transcript']
        self.assertEqual(transcript['stored_rows'],1)
        self.assertEqual(transcript['last_sequence'],4)

    def write_request(self, **changes):
        path=Path(self.call['_live_progress_dir'])/'retry.json'
        live_runtime.atomic_json(path,self.request(**changes))
        return path

    def write_route(self, **changes):
        data=dict(call_id=568,schedule_revision=7,expires_at=time.time()+60,
                  event_url='https://investors.example.test/events/current?eventid=123',
                  target_identity_verified=True)
        data.update(changes)
        live_runtime.atomic_json(self.root/'live-control'/'route-568.json',data)
        return data

    def test_attempt_context_is_stable_per_attempt_and_unique_between_attempts(self):
        first=live_runtime.prepare_attempt(self.call)
        meta=live_runtime.read_json(Path(self.call['_live_progress_dir'])/'attempt.json')
        self.assertEqual(first['STT_CAPTURE_SESSION_ID'],'session-A')
        self.assertEqual(meta['schedule_revision'],7)
        again=live_runtime.prepare_attempt(self.call)
        self.assertEqual(first,again)
        second={key:value for key,value in self.call.items() if not key.startswith('_live_')}
        other=live_runtime.prepare_attempt(second)
        self.assertNotEqual(first['WEBCAST_ATTEMPT_ID'],other['WEBCAST_ATTEMPT_ID'])
        self.assertNotEqual(first['WEBCAST_PROGRESS_DIR'],other['WEBCAST_PROGRESS_DIR'])

    def test_attempt_evidence_io_failure_does_not_block_capture_context(self):
        call={key:value for key,value in self.call.items() if not key.startswith('_live_')}
        with patch.object(live_runtime,'atomic_json',side_effect=OSError('disk full')),redirect_stderr(StringIO()):
            environment=live_runtime.prepare_attempt(call)
        self.assertTrue(environment['WEBCAST_ATTEMPT_ID'])
        self.assertEqual(environment['WEBCAST_CALL_DB_ID'],'568')
        self.assertEqual(environment['STT_CAPTURE_SESSION_ID'],'session-A')

    def test_request_is_accepted_once_for_exact_current_identity(self):
        path=self.write_request()
        self.assertEqual(live_runtime.consume_request(self.call,'retry')['request_id'],'request-A')
        self.assertIsNone(live_runtime.consume_request(self.call,'retry'))
        self.assertFalse(path.exists())
        self.assertFalse(list(path.parent.glob('*.claim-*.json')))

    def test_wrong_call_revision_attempt_or_session_and_ttl_are_rejected(self):
        mutations=[{'call_id':569},{'schedule_revision':6},{'attempt_id':'old-attempt'},
                   {'capture_session_id':'old-session'},
                   {'requested_at':(datetime.now(timezone.utc)-timedelta(seconds=121)).isoformat()},
                   {'requested_at':(datetime.now(timezone.utc)+timedelta(seconds=5)).isoformat()},
                   {'requested_at':datetime.now().isoformat()}, {'requested_at':'invalid'}]
        for change in mutations:
            with self.subTest(change=change):
                self.write_request(**change)
                self.assertIsNone(live_runtime.consume_request(self.call,'retry'))
        self.assertIsNone(live_runtime.consume_request(self.call,'../retry'))

    def test_concurrent_consumers_cannot_accept_one_request_twice(self):
        self.write_request()
        original=live_runtime.read_json
        barrier=threading.Barrier(2)
        def slow_old_read(path):
            value=original(path)
            # The previous read-then-unlink implementation let both threads
            # read this name. Atomic claim makes it unreachable to readers.
            if Path(path).name=='retry.json':
                barrier.wait(timeout=2)
            return value
        with patch.object(live_runtime,'read_json',side_effect=slow_old_read):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:live_runtime.consume_request(self.call,'retry'),range(2)))
        self.assertEqual(sum(result is not None for result in results),1)

    def test_new_request_written_during_consume_is_not_deleted(self):
        path=self.write_request()
        original=live_runtime.read_json
        inserted=False
        def replace_after_read(claimed):
            nonlocal inserted
            value=original(claimed)
            if not inserted and '.claim-' in Path(claimed).name:
                inserted=True
                live_runtime.atomic_json(path,self.request(request_id='request-B'))
            return value
        with patch.object(live_runtime,'read_json',side_effect=replace_after_read):
            first=live_runtime.consume_request(self.call,'retry')
        self.assertEqual(first['request_id'],'request-A')
        self.assertEqual(live_runtime.consume_request(self.call,'retry')['request_id'],'request-B')

    def test_route_hint_has_call_revision_ttl_and_exact_host_boundary(self):
        good=self.write_route()
        self.assertEqual(live_runtime.operator_route(self.call),good['event_url'])
        for change in ({'call_id':569},{'schedule_revision':6},{'expires_at':time.time()-1},
                       {'expires_at':'bad'},{'expires_at':float('nan')},{'expires_at':float('inf')},
                       {'event_url':'https://[invalid'},{'event_url':'https://user:pw@investors.example.test/e'},
                       {'event_url':'https://investors.example.test.attacker.test/e'},
                       {'event_url':'https://investors.example.test:9000/e'}, {'event_url':'file:///tmp/event'}):
            with self.subTest(change=change):
                self.write_route(**change)
                self.assertIsNone(live_runtime.operator_route(self.call))

    def test_memory_is_revision_date_and_provider_event_specific_with_ttl(self):
        first='https://provider.test/play?eventid=one'
        second='https://provider.test/play?eventid=two'
        with patch.object(live_runtime.time,'time',return_value=1000):
            live_runtime.remember(self.call,first,'identity_mismatch',ttl_seconds=60)
            live_runtime.remember(self.call,second,'auth_required',ttl_seconds=60)
            selected=live_runtime.remembered(self.call,{'identity_mismatch'})
            self.assertEqual(set(selected),{first})
            for change in ({'schedule_revision':8},{'earning_at':'2026-09-23'},{'schedule_discovery_fingerprint':'new'}):
                self.assertEqual(live_runtime.remembered({**self.call,**change},{'identity_mismatch'}),{})
        with patch.object(live_runtime.time,'time',return_value=1061):
            self.assertEqual(live_runtime.remembered(self.call,{'identity_mismatch','auth_required'}),{})

    def test_malformed_memory_and_write_errors_fail_closed(self):
        path=live_runtime.memory_path(self.call)
        for entries in ([],{'x':{'url':'https://provider.test/e','outcome':'auth_required','expires_at':'invalid'}},
                        {'x':{'url':'https://provider.test/e','outcome':['auth_required'],'expires_at':time.time()+10}}):
            live_runtime.atomic_json(path,{'entries':entries})
            self.assertEqual(live_runtime.remembered(self.call,{'auth_required'}),{})
        with patch.object(live_runtime,'atomic_json',side_effect=OSError('disk full')),redirect_stderr(StringIO()):
            live_runtime.remember(self.call,'https://provider.test/e','identity_mismatch')

    def test_memory_is_bounded_and_identity_fields_cannot_be_overridden(self):
        for i in range(130):
            live_runtime.remember(self.call,f'https://provider.test/e?id={i}','identity_mismatch',
                                  ttl_seconds=60,expires_at=float('inf'))
        entries=live_runtime.read_json(live_runtime.memory_path(self.call))['entries']
        self.assertEqual(len(entries),128)
        self.assertTrue(all(entry['expires_at'] < time.time()+61 for entry in entries.values()))

    def test_cli_identity_requires_current_revision_and_running_session(self):
        for revision,session in ((6,'session-A'),(7,None),(7,'session-B')):
            with self.assertRaises(ValueError):
                live_control.request_identity(self.call,revision,session)
        live_control.request_identity(self.call,7,'session-A')

    def test_current_attempt_never_falls_back_to_wrong_running_session(self):
        directory,meta=live_control.current_attempt(self.call)
        self.assertEqual(meta['capture_session_id'],'session-A')
        self.assertEqual(directory,Path(self.call['_live_progress_dir']))
        self.assertEqual(live_control.current_attempt({**self.call,'capture_session_id':'session-B'}),(None,{}))
        self.assertEqual(live_control.current_attempt({**self.call,'schedule_revision':8}),(None,{}))

    def test_cli_route_is_only_an_unverified_hint_and_does_not_clear_wait(self):
        call={**self.call,'status':'upcoming','capture_session_id':None}
        with patch.object(live_control,'fetch_call',return_value=call), \
             patch.object(live_control,'record_event'),patch.object(live_control.engine,'begin') as transaction,redirect_stdout(StringIO()):
            self.assertEqual(live_control.main(['route','--call-id','568','--expected-revision','7',
                '--event-url','https://investors.example.test/events/today']),0)
        self.assertFalse(transaction.called)
        hint=live_runtime.read_json(self.root/'live-control'/'route-568.json')
        self.assertFalse(hint['target_identity_verified'])
        self.assertEqual(hint['source'],'operator_unverified_hint')

    def test_cli_pending_future_wait_and_active_probe_are_not_overridden(self):
        base={**self.call,'status':'upcoming','capture_session_id':None,'stream_probe_status':'pending',
              'stream_probe_retry_reason':'scheduled_start_wait',
              'stream_probe_retry_not_before':datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=10)}
        for change in ({},{'stream_probe_status':'probing'}):
            with patch.object(live_control,'fetch_call',return_value={**base,**change}), \
                 patch.object(live_control.engine,'begin') as transaction,self.assertRaises(ValueError):
                live_control.main(['retry','--call-id','568','--expected-revision','7'])
            self.assertFalse(transaction.called)

    def test_cli_failed_atomic_claim_does_not_report_recovery_applied(self):
        call={**self.call,'status':'upcoming','capture_session_id':None,'stream_probe_status':'pending'}
        with patch.object(live_control,'fetch_call',return_value=call), \
             patch.object(live_control.engine,'begin') as transaction,patch.object(live_control,'record_event') as event:
            transaction.return_value.__enter__.return_value.execute.return_value.rowcount=0
            with self.assertRaisesRegex(ValueError,'changed or remains owned'):
                live_control.main(['retry','--call-id','568','--expected-revision','7'])
        self.assertFalse(event.called)

    def test_operator_entrypoint_never_inherits_verified_flag(self):
        route=self.write_route()['event_url']
        call={**self.call,'_live_entrypoint_kind':'operator_event_url','_live_entrypoint_url':route,
              '_live_discovery_proof':{'verified':True,'target_url':route,'target_date':'2026-09-22',
                  'call_ticker':'AZO','source_url':self.call['ir_url'],'evidence':'current call',
                  'observed_at':datetime.now(timezone.utc).isoformat()}}
        environment=STTWorkerManager()._probe_runtime_environment(call,{'WEBCAST_LIVE_ENTRYPOINT_VERIFIED':'true',
                                                                     'WEBCAST_LIVE_IDENTITY_PROOF':'injected'})
        self.assertEqual(environment['WEBCAST_LIVE_ENTRYPOINT_VERIFIED'],'false')
        self.assertNotIn('WEBCAST_LIVE_IDENTITY_PROOF',environment)
        self.assertEqual(environment['WEBCAST_DIRECT_TARGET_URL'],'')


class DiscoveryHintVerificationTest(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_child_is_unverified_and_wrong_date_proof_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(live_runtime,'runtime_root',return_value=Path(directory)), \
             patch.dict(os.environ,{'WEBCAST_CAPTURE_RUNNER':'container','WEBCAST_HEADED':'false','DATE_STREAM_DISCOVERY_HEADED':'false'}):
            call=dict(id=568,ticker='AZO',schedule_revision=7,earning_at='2026-09-22',ir_url='https://investors.example.test/events')
            hint='https://investors.example.test/events/today'
            live_runtime.atomic_json(Path(directory)/'live-control'/'route-568.json',
                dict(call_id=568,schedule_revision=7,expires_at=time.time()+60,event_url=hint,target_identity_verified=True))
            launches=[]
            async def launch(*command,**kwargs):
                launches.append((command,kwargs['env']))
                stream=asyncio.StreamReader()
                payload={'target_identity_verified':True,'discovered_url':hint,
                         'identity_proof':{'verified':True,'call_ticker':'AZO','target_url':hint,
                             'target_date':'2026-08-22','source_url':call['ir_url'],'evidence':'old call',
                             'observed_at':datetime.now(timezone.utc).isoformat()}}
                stream.feed_data(('WEBCAST_DISCOVERY_RESULT='+json.dumps(payload)+'\n').encode())
                stream.feed_eof()
                class Process:
                    returncode=0
                    stdout=stream
                    async def wait(self): return 0
                return Process()
            with patch('data_pipeline.stt_worker.manager.asyncio.create_subprocess_exec',side_effect=launch):
                result=await STTWorkerManager().discover_date_based_call(call)
            self.assertFalse(result['target_identity_verified'])
            self.assertTrue(launches)
            self.assertIn(hint,launches[0][0])
            for _,environment in launches:
                self.assertEqual(environment['WEBCAST_LIVE_ENTRYPOINT_VERIFIED'],'false')
                self.assertEqual(environment['WEBCAST_LIVE_IDENTITY_PROOF'],'')
                self.assertEqual(environment['WEBCAST_REQUIRE_LIVE_TARGET_CONFIRMATION'],'true')
                self.assertEqual(environment['WEBCAST_ALLOW_REGISTRATION_SUBMISSION'],'false')


if __name__=='__main__':
    unittest.main()
