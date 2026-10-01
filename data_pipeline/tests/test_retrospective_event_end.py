"""Real SQL checks for ended-event reconciliation, using local proof files."""
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from sqlalchemy import create_engine, event, text
from data_pipeline.storage import live_calls, schedules, schema


class SQLiteEndEngine:
    def __init__(self):
        self.raw = create_engine('sqlite://')
        @event.listens_for(self.raw, 'connect')
        def add_functions(db, _):
            db.create_function('CHAR_LENGTH', 1, lambda s: len(s) if s is not None else None)
            db.create_function('GREATEST', -1, lambda *xs: max(xs) if all(x is not None for x in xs) else None)
        @event.listens_for(self.raw, 'before_cursor_execute', retval=True)
        def dialect(conn, cursor, statement, params, context, many):
            # Keep predicates/assignments intact; adapt MySQL syntax only.
            statement = re.sub(r'\bFOR UPDATE\b', '', statement).replace('<=>', 'IS')
            statement = re.sub(r'ON DUPLICATE KEY UPDATE', 'ON CONFLICT(ticker,call_year,quarter) DO UPDATE SET', statement)
            statement = re.sub(r'\bVALUES\((\w+)\)', r'excluded.\1', statement)
            statement = re.sub(r'\bIF\(', 'IIF(', statement)
            return statement, params
        with self.raw.begin() as conn:
            fields = ','.join(f'{key} {value}' for key,value in schema.SCHEDULE_TIME_COLUMNS.items())
            conn.execute(text("CREATE TABLE calls(id INTEGER PRIMARY KEY,ticker TEXT,earning_at DATETIME,call_year INTEGER,quarter TEXT,status TEXT,video_url TEXT,"+fields+",UNIQUE(ticker,call_year,quarter))"))
            conn.execute(text('CREATE TABLE transcript_segments(call_id TEXT,sequence_no INTEGER,text_chunk TEXT,target_identity_verified BOOLEAN)'))
            conn.execute(text('CREATE TABLE schedule_change_history(id INTEGER PRIMARY KEY,call_id INTEGER,revision INTEGER,reason TEXT,observed_at DATETIME,before_json TEXT,after_json TEXT)'))
            conn.execute(text('CREATE TABLE stocks(ticker TEXT,company_name TEXT,ir_url TEXT)'))

    def begin(self):
        return self.raw.begin()

    def connect(self):
        return self.raw.connect()


class RetrospectiveEventEndTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.directory=Path(self.stack.enter_context(TemporaryDirectory()))
        self.engine=SQLiteEndEngine();self.addCleanup(self.engine.raw.dispose)
        self.stack.enter_context(mock.patch.object(live_calls.connection,'engine',self.engine))
        self.stack.enter_context(mock.patch.object(schema,'ensure_schedule_time_schema'))
        self.stack.enter_context(mock.patch.object(schema,'ensure_transcript_archive_schema'))
        self.now=datetime.now(timezone.utc).replace(tzinfo=None)
        self.day=self.now.date()-timedelta(days=1)
        self.session='GIS-capture-218-fixture'
        self.url='https://events.q4inc.com/attendee/fixture-event'
        self.source=self.directory/'capture.log';self.source.write_text('fixture original observation and transcript archive\n')
        self.source2=self.directory/'later-observation.log';self.source2.write_text('fixture later observation of the same end status\n')
        self.proof={'version':1,'reason':'event_ended','evidence_kind':'browser_event_status',
                    'capture_session_id':self.session,'schedule_revision':4,'ticker':'GIS',
                    'target_date':self.day.isoformat(),'event_url':self.url,
                    'target_identity_verified':True,'observed_at':self.now.isoformat(),
                    'coverage':'partial','evidence':'This event has ended.','observations':2,
                    'sources':[{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
                               for source in (self.source,self.source2)]}
        with self.engine.begin() as conn:
            conn.execute(text('''INSERT INTO calls(id,ticker,earning_at,call_year,quarter,status,webcast_date,
                schedule_revision,capture_session_id,webcast_url,event_url)
                VALUES(218,'GIS',:day,:year,:quarter,'upcoming',:day,4,:session,:url,'https://issuer.test/event')'''),
                {'day':self.day,'year':self.day.year,'quarter':f'Q{(self.day.month-1)//3+1}','session':self.session,'url':self.url})
            conn.execute(text('INSERT INTO transcript_segments VALUES(:session,301,:body,0),(:session,302,:closing,0),(:session,303,:noise,1)'),
                         {'session':self.session,'body':'Substantive earnings discussion was captured.',
                          'closing':'This brings us to the end of today’s meeting. You may now disconnect.', 'noise':'BORNAN BOR.'})
            conn.execute(text("INSERT INTO stocks VALUES('GIS','General Mills','https://issuer.test')"))

    def update(self, **values):
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE calls SET '+','.join(f'{key}=:{key}' for key in values)+' WHERE id=218'),values)

    def row(self):
        with self.engine.connect() as conn:
            return dict(conn.execute(text('SELECT * FROM calls WHERE id=218')).mappings().one())

    def apply(self, **overrides):
        path=self.directory/'proof.json';path.write_text(json.dumps(self.proof,ensure_ascii=False))
        params={'expected_capture_session_id':self.session,'expected_schedule_revision':4,
                'expected_event_date':self.day,'expected_event_url':self.url,
                'evidence_path':str(path),'evidence_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        return live_calls.record_verified_call_event_end(218,**{**params,**overrides})

    def operator(self):
        self.proof.update(evidence_kind='operator_closing',terminal_sequence=302,
                          no_following_speech_seconds=600,coverage='unverified',
                          evidence='This brings us to the end of today’s meeting. You may now disconnect.')

    def test_partial_browser_evidence_stops_retry_without_completing_or_changing_text(self):
        result=self.apply()
        self.assertTrue(result['recorded'])
        self.assertEqual((result['status'],result['coverage'],result['segment_count']),('ended','partial',3))
        self.assertEqual(self.row()['status'],'ended')
        self.assertEqual(self.row()['stream_probe_retry_reason'],'event_ended')
        self.assertIn('COVERAGE_UNVERIFIED',self.row()['capture_last_error'])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT text_chunk FROM transcript_segments ORDER BY sequence_no DESC LIMIT 1')).scalar(),'BORNAN BOR.')

    def test_operator_closing_allows_tiny_noise_without_rewriting_it(self):
        self.operator();self.assertTrue(self.apply()['recorded'])

    def test_actual_q4_broadcast_end_message_is_accepted(self):
        self.proof['evidence']='Broadcast has ended, thanks for watching!'
        self.assertTrue(self.apply()['recorded'])

    def test_two_browser_observations_require_distinct_source_files(self):
        self.proof['sources']=self.proof['sources'][:1]
        self.assertFalse(self.apply()['recorded'])
        self.proof['sources']*=2
        self.assertFalse(self.apply()['recorded'])

    def test_renewed_substantive_speech_rejects_closing(self):
        self.operator()
        for speech in ('One more question on revenues', 'Please hold', 'Another question?', 'Don’t disconnect'):
            with self.subTest(speech=speech),self.engine.begin() as conn:
                conn.execute(text('UPDATE transcript_segments SET text_chunk=:speech WHERE sequence_no=303'),{'speech':speech})
            self.assertEqual(self.apply()['reason'],'transcript_closing_not_terminal')
            self.assertEqual(self.row()['status'],'upcoming')

    def test_operator_closing_requires_same_archived_text_and_verified_identity(self):
        self.operator();self.proof['evidence'] += ' Thank you.'
        self.assertEqual(self.apply()['reason'],'transcript_closing_not_terminal')
        self.operator()
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE transcript_segments SET target_identity_verified=0'))
        self.assertEqual(self.apply()['reason'],'transcript_closing_not_terminal')

    def test_silence_generic_thanks_and_single_dom_observation_do_not_stop_retry(self):
        for patch in ({'evidence':'Thank you for participating.'}, {'observations':1},
                      {'evidence_kind':'silence'}, {'target_identity_verified':False}, {'coverage':'complete'}):
            with self.subTest(patch=patch):
                old=dict(self.proof);self.proof.update(patch)
                self.assertFalse(self.apply()['recorded']);self.proof=old
        self.operator()
        for idle in (0,59,float('nan')):
            self.proof['no_following_speech_seconds']=idle
            self.assertFalse(self.apply()['recorded'])

    def test_identity_revision_date_session_url_and_ticker_guard(self):
        for values in ({'schedule_revision':5},{'webcast_date':self.day+timedelta(days=1)},
                       {'capture_session_id':'new-session'},{'webcast_url':'https://events.q4inc.com/attendee/other'},
                       {'ticker':'PAYX'},{'schedule_superseded_by':9}):
            with self.subTest(values=values):
                before=self.row();self.update(**values)
                self.assertEqual(self.apply()['reason'],'current_call_identity_changed')
                self.update(**{key:before[key] for key in values})

    def test_live_capture_or_either_live_lease_is_not_stopped(self):
        for values in ({'status':'running'}, {'capture_lease_until':self.now+timedelta(minutes=1)},
                       {'stream_probe_lease_until':self.now+timedelta(minutes=1)}):
            with self.subTest(values=values):
                before=self.row();self.update(**values)
                self.assertFalse(self.apply()['recorded'])
                self.update(**{key:before[key] for key in values})

    def test_inactive_expired_lease_can_reconcile(self):
        self.update(capture_lease_until=self.now-timedelta(seconds=5),stream_probe_lease_until=self.now-timedelta(seconds=5))
        self.assertTrue(self.apply()['recorded'])

    def test_source_and_manifest_hashes_must_still_match(self):
        self.assertFalse(self.apply(evidence_sha256='0'*64)['recorded'])
        self.source.write_text('changed after review')
        self.assertFalse(self.apply()['recorded'])

    def test_end_observation_must_follow_event_and_not_be_future_or_missing(self):
        for observed in (None,(self.now+timedelta(minutes=5)).isoformat(),
                         (datetime.combine(self.day,datetime.min.time())-timedelta(days=2)).isoformat()):
            with self.subTest(observed=observed):
                self.proof['observed_at']=observed
                self.assertFalse(self.apply()['recorded'])

    def test_repeated_identical_reconcile_is_idempotent_and_completed_is_not_downgraded(self):
        self.assertTrue(self.apply()['recorded']);audit=self.row()['capture_last_error']
        self.assertEqual(self.apply()['reason'],'already_ended')
        self.assertEqual(self.row()['capture_last_error'],audit)
        self.update(status='completed')
        self.assertEqual(self.apply()['reason'],'call_not_retryable')
        self.assertEqual(self.row()['status'],'completed')

    def test_exact_start_later_than_observed_end_rejects(self):
        self.update(scheduled_at_utc=self.now+timedelta(minutes=2))
        self.assertEqual(self.apply()['reason'],'end_precedes_scheduled_start')

    def test_ended_call_is_excluded_from_dispatch(self):
        self.assertTrue(self.apply()['recorded'])
        calls=live_calls.get_date_based_stream_candidates(reference_time_utc=self.now.replace(tzinfo=timezone.utc))
        self.assertEqual(calls,[])

    def test_yahoo_refresh_cannot_resurrect_ended_event_or_remove_identity(self):
        self.assertTrue(self.apply()['recorded'])
        original=self.row()
        for incoming in (self.day,self.day+timedelta(days=1)):
            schedules.save_earnings_schedules([{'ticker':'GIS','earning_date':incoming}],observed_at=self.now+timedelta(minutes=1))
            row=self.row()
            for key in ('status','capture_session_id','schedule_revision','earning_at','webcast_date','webcast_url','capture_last_error'):
                self.assertEqual(row[key],original[key],key)

    def test_future_distinct_quarter_is_still_inserted_upcoming(self):
        self.assertTrue(self.apply()['recorded'])
        future=self.day+timedelta(days=95)
        schedules.save_earnings_schedules([{'ticker':'GIS','earning_date':future}],observed_at=self.now)
        with self.engine.connect() as conn:
            rows=conn.execute(text('SELECT status FROM calls ORDER BY id')).scalars().all()
        self.assertEqual(rows,['ended','upcoming'])

    def test_nasdaq_only_refresh_preserves_ended_identity_and_outcome(self):
        self.assertTrue(self.apply()['recorded'])
        original=self.row()
        schedules.reconcile_near_term_schedule_sources(
            [{'ticker':'GIS','earning_date':self.day}],yahoo_observed_at=self.now,
            nasdaq_fetched_dates={self.day},start_date=self.day,days_ahead=1,observed_at=self.now)
        row=self.row()
        for key in ('status','capture_session_id','schedule_revision','earning_at','webcast_date','webcast_url','capture_last_error'):
            self.assertEqual(row[key],original[key],key)

    def test_official_enrichment_cannot_reopen_or_change_ended_revision(self):
        self.assertTrue(self.apply()['recorded'])
        result=schedules.update_verified_schedule_time(218,{'expected_revision':4,'observed_at':self.now,
            'scheduled_at_utc':self.now+timedelta(days=1),'webcast_date':self.day+timedelta(days=1)})
        self.assertIsNone(result)
        self.assertEqual(self.row()['status'],'ended')
        self.assertEqual(self.row()['schedule_revision'],4)

    def lineage(self, **changes):
        self.operator()
        attempt={'call_id':218,'ticker':'GIS','schedule_revision':4,
                 'capture_session_id':self.session,'attempt_id':'original-attempt',
                 'event_date':self.day.isoformat(),'created_at':(self.now-timedelta(hours=2)).isoformat(),**changes}
        path=self.directory/'original-attempt.json';path.write_text(json.dumps(attempt))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        self.proof['sources']=[source for source in self.proof['sources'] if source['path']!=str(path)]
        self.proof['sources'].append({'path':str(path),'sha256':digest})
        self.update(capture_session_id='later-replay-session',capture_manifest_path='/runtime/later-replay/manifest.json')
        return {'expected_capture_session_id':'later-replay-session','evidence_capture_session_id':self.session,
                'evidence_attempt_path':str(path),'evidence_attempt_sha256':digest}

    def test_original_live_end_can_stop_later_replay_without_relabelling_evidence(self):
        params=self.lineage()
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO transcript_segments VALUES('later-replay-session',0,'Replay welcome speech remains archived',1)"))
        result=self.apply(**params)
        self.assertTrue(result['recorded'])
        self.assertEqual(result['canonical_capture_session_id'],self.session)
        row=self.row();self.assertEqual(row['capture_session_id'],self.session)
        self.assertIsNone(row['capture_manifest_path'])
        audit=json.loads(row['capture_last_error'])
        self.assertEqual(audit['superseded_capture_session_id'],'later-replay-session')
        self.assertEqual(audit['canonical_capture_session_id'],self.session)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM transcript_segments WHERE call_id='later-replay-session'")).scalar(),1)
        self.assertEqual(self.apply(**params)['reason'],'already_ended')

    def test_original_attempt_must_bind_every_event_and_session_identity(self):
        for values in ({'call_id':875},{'ticker':'PAYX'},{'schedule_revision':3},
                       {'event_date':(self.day-timedelta(days=1)).isoformat()},
                       {'capture_session_id':'different-original-session'},
                       {'created_at':(self.now+timedelta(seconds=1)).isoformat()}):
            with self.subTest(values=values):
                params=self.lineage(**values)
                self.assertEqual(self.apply(**params)['reason'],'original_attempt_identity_mismatch')
                self.assertEqual(self.row()['capture_session_id'],'later-replay-session')

    def test_original_lineage_requires_original_artifact_in_hashed_sources(self):
        params=self.lineage()
        self.proof['sources']=self.proof['sources'][:2]
        self.assertEqual(self.apply(**params)['reason'],'missing_original_attempt_lineage')
        params=self.lineage();params.pop('evidence_attempt_path')
        self.assertFalse(self.apply(**params)['recorded'])

    def test_live_replay_capture_must_stop_before_canonical_session_is_restored(self):
        params=self.lineage();self.update(status='running')
        self.assertEqual(self.apply(**params)['reason'],'active_capture')
        self.assertEqual(self.row()['capture_session_id'],'later-replay-session')


if __name__=='__main__':
    unittest.main()
