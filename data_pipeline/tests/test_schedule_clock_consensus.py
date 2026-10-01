"""Durable clock conflicts exercised through repository -> watcher -> SQL.

Set EW_CLOCK_TEST_DB_URL only to the isolated ew_clock_test database to run the
same suite on MySQL. No production schema or network lookup is used.
"""
from datetime import date, datetime, timedelta, timezone
import json
import os
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from sqlalchemy import create_engine, event, text
from data_pipeline.storage import schedules, live_calls, schema, policies
from data_pipeline.application.live_watch import LiveWatchService
from data_pipeline.collectors.schedules.browser_observation import (
    observe_browser_time, validated_browser_values, proof_extends_route)
from data_pipeline.collectors.schedules.clock_reconciliation import reconcile_clock_observations
from data_pipeline.collectors.schedules.event_routes import route_proof
from data_pipeline.tests.test_schedule_revision_storage import SQLiteScheduleEngine

IR = 'https://issuer.test/events/event-details/q1'
PLAYER = 'https://events.q4inc.com/attendee/387216736'


class ClockConsensusRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.day = self.now.date()
        self.origin = (self.now - timedelta(minutes=5)).replace(microsecond=0)
        database = os.getenv('EW_CLOCK_TEST_DB_URL')
        if database:
            from sqlalchemy.engine import make_url
            parsed = make_url(database)
            if parsed.database != 'ew_clock_test' or parsed.host != 'ew-clock-mysql-20261002':
                raise RuntimeError('Only the dedicated isolated clock-test database is allowed')
            self.raw = create_engine(database)
            self.engine = self.raw
            with self.raw.begin() as conn:
                for name in ('schedule_change_history', 'transcript_segments', 'stocks', 'calls'):
                    conn.execute(text('DROP TABLE IF EXISTS '+name))
                fields = ', '.join(f'{name} {definition}' for name, definition in schema.SCHEDULE_TIME_COLUMNS.items())
                conn.execute(text("CREATE TABLE calls (id INTEGER PRIMARY KEY, ticker VARCHAR(20), earning_at DATE, call_year INTEGER, quarter VARCHAR(10), status VARCHAR(20) DEFAULT 'upcoming', video_url TEXT, "+fields+')'))
                conn.execute(text('CREATE TABLE transcript_segments (call_id VARCHAR(20), text_chunk TEXT)'))
                conn.execute(text('CREATE TABLE stocks (ticker VARCHAR(20), company_name TEXT, ir_url TEXT)'))
                conn.execute(text('CREATE TABLE schedule_change_history (id INTEGER AUTO_INCREMENT PRIMARY KEY, call_id INTEGER, revision INTEGER, reason VARCHAR(64), observed_at DATETIME, before_json LONGTEXT, after_json LONGTEXT)'))
        else:
            self.engine = SQLiteScheduleEngine()
            self.raw = self.engine.raw
            @event.listens_for(self.raw, 'before_cursor_execute', retval=True)
            def sqlite_dates(conn, cursor, statement, parameters, context, executemany):
                statement = re.sub(r'DATE_(ADD|SUB)\(\s*UTC_TIMESTAMP\(\),\s*INTERVAL\s+(\d+)\s+MINUTE\s*\)',
                    lambda m: "datetime(CURRENT_TIMESTAMP, '"+('+' if m[1]=='ADD' else '-')+m[2]+" minutes')", statement)
                return statement.replace('UTC_TIMESTAMP()', 'CURRENT_TIMESTAMP'), parameters
        self.addCleanup(self.raw.dispose)
        for target, name, value in ((schedules.connection, 'engine', self.engine),
                                   (schema, 'ensure_schedule_time_schema', lambda: None)):
            p = patch.object(target,name,value);p.start();self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'PIPELINE_WORKER_ID':'clock-consensus-test',
                                   'DATE_STREAM_EARLY_ENTRY_MINUTES':'5'})
        p.start();self.addCleanup(p.stop)
        p = patch('data_pipeline.application.live_watch.live_runtime.record')
        p.start();self.addCleanup(p.stop)
        self.service = LiveWatchService(live_calls, SimpleNamespace(), SimpleNamespace(), Mock())
        with self.raw.begin() as conn:
            conn.execute(text("INSERT INTO stocks(ticker,company_name,ir_url) VALUES('EXM','Example Corporation',:url)"),{'url':IR})
            conn.execute(text("INSERT INTO calls(id,ticker,earning_at,webcast_date,call_year,quarter,verified_fiscal_year,verified_fiscal_quarter,event_url,schedule_revision) VALUES(1,'EXM',:day,:day,2027,'Q1',2027,'Q1',:url,0)"),{'day':self.day,'url':IR})

    def row(self):
        with self.raw.connect() as conn:
            return dict(conn.execute(text('SELECT * FROM calls WHERE id=1')).mappings().one())

    def update(self, **values):
        with self.raw.begin() as conn:
            conn.execute(text('UPDATE calls SET '+','.join(f'{key}=:{key}' for key in values)+' WHERE id=1'),values)

    def context(self):
        return schedules.get_call_schedule_context(1)

    def clock_text(self,hour):
        return f'Example Corporation EXM Q1 2027 earnings call {self.day:%B %d, %Y} at {hour}:00 PM GMT'

    def proof(self,provider=False):
        original = dict(verified=True,call_ticker='EXM',target_date=str(self.day),
            source_url=IR,target_url=IR,target_kind='event_detail',
            observed_at=self.origin.isoformat(),source_observed_at=self.origin.isoformat(),
            evidence=self.clock_text(10))
        if provider:
            original.update(target_url=PLAYER,target_kind='provider',observed_at=datetime.now(timezone.utc).isoformat(),
                route_lineage=[dict(parent_target_url=IR,target_url=PLAYER,kind='selected_link',observed_at=self.now.isoformat())])
        return original

    def observe(self,hour,provider=False):
        agent = SimpleNamespace(lifecycle='live',ticker='EXM',target_date=self.day,
            target_year=2027,target_quarter='Q1',live_target_proof=self.proof(provider))
        return observe_browser_time(agent,self.clock_text(hour),evidence_url=PLAYER if provider else IR)

    def seed_conflict(self):
        clocks = [dict(source=url,value=datetime.combine(self.day,datetime.min.time()).replace(hour=hour,tzinfo=timezone.utc).isoformat(),
                       observed_at=self.origin.isoformat(),source_timezone='GMT',evidence=self.clock_text(hour-12))
                  for url,hour in ((IR,22),(PLAYER,21))]
        rp=route_proof(ticker='EXM',day=self.day,issuer_url=IR,event_url=IR,webcast_url=PLAYER,fiscal_year=2027,fiscal_quarter='Q1')
        self.update(schedule_revision=2,scheduled_at_utc=None,time_verified_at=None,time_verification_status='unverified',
            schedule_observed_at=self.origin.replace(tzinfo=None),schedule_revalidation_status='provisional_watch',
            schedule_revalidation_reason='ambiguous_call_time',webcast_url=PLAYER,
            schedule_discovery_fingerprint='b'*64,schedule_discovery_checked_at=self.origin.replace(tzinfo=None),
            schedule_evidence=rp+' '+self.clock_text(10),schedule_source='official_ir_event',
            schedule_revalidation_evidence=json.dumps(dict(clock_state='conflicted',clock_validation_version=1,
                clock_observations=clocks,clock_conflict_started_at=self.origin.isoformat(),required_clock_sources=[IR,PLAYER],
                conflict_kind='start_time_conflict',route_identity_verified=True,route_action='retained')))

    def probe(self,observation,ready=False,error=None):
        call=self.context() # real repository projection, not a hand-built schedule
        self.update(stream_probe_status='probing',stream_probe_lease_owner=live_calls._pipeline_worker_id(),
            stream_probe_lease_until=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=5),
            last_stream_probe_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1))
        call.update(_browser_schedule_observation=observation,_live_discovery_proof=self.proof())
        return self.service._record_probe(1,call=call,stream_ready=ready,
            error=None if ready else (error or 'NOT_LIVE_YET waiting'),watch_state='event_window',expected_date=self.day)

    def assert_conflicted(self):
        row=self.row()
        self.assertIsNone(row['scheduled_at_utc'])
        self.assertEqual(row['schedule_revalidation_status'],'provisional_watch')
        self.assertEqual(row['schedule_revalidation_reason'],'ambiguous_call_time')
        return json.loads(row['schedule_revalidation_evidence'])

    def test_issuer_only_browser_cannot_clear_existing_provider_conflict_or_erase_route(self):
        self.seed_conflict();before=self.row()
        result=self.probe(self.observe(10))
        clocks=self.assert_conflicted()
        self.assertTrue(result['schedule_conflicted'])
        self.assertEqual({x['source'] for x in clocks['clock_observations']},{IR,PLAYER})
        self.assertEqual(self.row()['webcast_url'],PLAYER)
        self.assertEqual(self.row()['schedule_discovery_checked_at'],before['schedule_discovery_checked_at'])
        self.assertNotEqual(self.row()['stream_probe_retry_reason'],'scheduled_start_wait')

    def test_provider_lineage_clock_is_committed_as_conflict_after_incorrect_legacy_verified_clock(self):
        self.update(scheduled_at_utc=datetime.combine(self.day,datetime.min.time()).replace(hour=22),
            time_verification_status='verified',time_verified_at=self.origin.replace(tzinfo=None),
            schedule_source='official_browser_event',schedule_evidence=self.clock_text(10),
            webcast_url=IR,source_timezone='GMT',
            stream_probe_retry_not_before=datetime.combine(self.day,datetime.min.time()).replace(hour=21,minute=55),
            stream_probe_retry_reason='scheduled_start_wait')
        result=self.probe(self.observe(9,True))
        clocks=self.assert_conflicted()
        self.assertTrue(result['schedule_conflicted'])
        self.assertEqual({x['value'][11:13] for x in clocks['clock_observations']},{'21','22'})
        self.assertEqual(self.row()['webcast_url'],PLAYER)
        retry=self.row()['stream_probe_retry_not_before']
        self.assertTrue(retry is None or schedules._utc_naive(retry) <= datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=2))
        # Provider time cannot renew the original issuer route proof.
        self.assertEqual(schedules._utc_naive(self.row()['schedule_discovery_checked_at']).replace(microsecond=0),self.origin.replace(tzinfo=None,microsecond=0))

    def test_each_source_must_be_freshly_reobserved_before_consensus_clears(self):
        self.seed_conflict()
        # Old stored provider happens to agree with fresh issuer: not sufficient.
        self.probe(self.observe(9))
        self.assert_conflicted()
        # A new provider reading now supplies the missing side at same instant.
        result=self.probe(self.observe(9,True))
        self.assertTrue(result['schedule_applied'])
        self.assertEqual(self.row()['time_verification_status'],'verified')
        self.assertEqual(schedules._utc_naive(self.row()['scheduled_at_utc']).hour,21)

    def test_repeated_provider_only_cannot_clear_missing_issuer(self):
        self.seed_conflict()
        for _ in range(2):
            self.probe(self.observe(9,True));self.assert_conflicted()

    def test_confirmed_live_audio_can_handoff_while_clock_conflict_stays_unresolved(self):
        self.seed_conflict()
        self.probe(self.observe(9,True)) # route changes may require one revision
        result=self.probe(self.observe(9,True),ready=True)
        self.assertTrue(result['capture_handoff_valid'])
        self.assert_conflicted()

    def test_route_and_date_only_refresh_do_not_drop_clock_conflict(self):
        self.seed_conflict()
        context=self.context()
        schedules.update_official_schedule_discovery(1,webcast_date=self.day,event_url=IR,webcast_url=PLAYER,
            source='official_ir_event',evidence=context['schedule_evidence'],fingerprint='b'*64,
            expected_revision=context['schedule_revision'],observed_at=datetime.now(timezone.utc))
        self.assert_conflicted()
        context=self.context()
        schedules.confirm_schedule_revalidation_from_official_ir(1,event_url=IR,evidence='Time to be announced',
            webcast_date=self.day,expected_revision=context['schedule_revision'],observed_at=datetime.now(timezone.utc))
        self.assert_conflicted()

    def test_unresolved_later_issuer_clock_cannot_restore_a_delayed_wait(self):
        self.seed_conflict()
        late=datetime.combine(self.day,datetime.min.time()).replace(hour=22)
        marker='NOT_LIVE_YET scheduled event time is in the future: '+late.isoformat()+'Z'
        for _ in range(2):
            result=self.probe(self.observe(10),error=marker)
            self.assert_conflicted()
            self.assertEqual(result['reason'],'schedule_clock_conflict')
            self.assertNotEqual(self.row()['stream_probe_retry_reason'],'scheduled_start_wait')
            retry=self.row()['stream_probe_retry_not_before']
            self.assertTrue(retry is None or schedules._utc_naive(retry) <= datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=2))

    def test_unchained_or_expired_provider_observation_is_rejected_before_sql(self):
        self.seed_conflict()
        for mutate in (lambda x:x['identity_proof'].pop('route_lineage'),
                       lambda x:x['identity_proof'].update(source_observed_at=(self.now-timedelta(hours=7)).isoformat())):
            observation=self.observe(9,True);mutate(observation)
            call=self.context();call['_live_discovery_proof']=self.proof()
            self.assertIsNone(validated_browser_values(call,observation))

    def test_unknown_legacy_sources_cannot_be_cleared_by_repeated_single_source(self):
        self.seed_conflict();self.update(schedule_revalidation_evidence='{}')
        for _ in range(2):
            self.probe(self.observe(9,True));self.assert_conflicted()


class ClockEvidenceValidationTest(unittest.TestCase):
    def test_known_provider_heading_only_clock_requires_authenticated_full_identity(self):
        from data_pipeline.collectors.schedules.call_times import parse_call_times
        actual = ('Accenture Fourth Quarter Fiscal 2026 Earnings Thursday, '
                  'October 01, 2026 8:00 AM Eastern Daylight Time 1 hour Register Now!')
        kwargs = dict(expected_fiscal_year=2026,expected_fiscal_quarter='Q4',grace_days=0)
        day=date(2026,10,1)
        self.assertIsNone(parse_call_times(actual,day,**kwargs).selected)
        accepted=parse_call_times(actual,day,authenticated_provider=True,**kwargs).selected
        self.assertEqual(accepted.scheduled_at_utc,datetime(2026,10,1,12,tzinfo=timezone.utc))
        self.assertEqual(accepted.evidence,actual)
        for text_value in (actual.replace('Earnings','Earnings Release'),
                           actual.replace('Earnings','Earnings Replay'),
                           actual.replace('Earnings','Investor Day Earnings'),
                           actual.replace('2026 Earnings','2025 Earnings'),
                           actual.replace('October 01','October 02'),
                           actual.replace('Eastern Daylight Time','')):
            with self.subTest(text=text_value):
                self.assertIsNone(parse_call_times(text_value,day,authenticated_provider=True,**kwargs).selected)
        self.assertIsNone(parse_call_times(actual,day,authenticated_provider=True).selected)

    def test_lineage_rejects_gap_foreign_source_or_origin_renewal(self):
        now=datetime.now(timezone.utc)
        old=dict(target_url=IR,source_url=IR,source_observed_at=(now-timedelta(minutes=5)).isoformat())
        new={**old,'target_url':PLAYER,'route_lineage':[dict(parent_target_url=IR,target_url=PLAYER,
            observed_at=now.isoformat(),kind='selected_link')]}
        self.assertTrue(proof_extends_route(old,new,now=now))
        for mutation in ({'source_url':'https://foreign.test'},
                         {'source_observed_at':now.isoformat()},
                         {'route_lineage':[{**new['route_lineage'][0],'parent_target_url':'https://issuer.test/other'}]},
                         {'route_lineage':[{**new['route_lineage'][0],'observed_at':(now-timedelta(hours=7)).isoformat()}]},
                         {'route_lineage':[{**new['route_lineage'][0],'target_url':'https://events.q4inc.com/attendee/111'}]}):
            self.assertFalse(proof_extends_route(old,{**new,**mutation},now=now))
        # A separate fresh issuer observation may corroborate the same route.
        self.assertTrue(proof_extends_route(new,{**new,'source_observed_at':now.isoformat()},now=now))

    def test_equal_time_same_source_internal_contradiction_cannot_be_collapsed(self):
        now=datetime.now(timezone.utc)
        observations=[dict(source=IR,value=now.replace(hour=h).isoformat(),observed_at=now.isoformat()) for h in (21,22)]
        result=reconcile_clock_observations({},observations,observed_at=now)
        self.assertTrue(result['conflicted'])
        self.assertEqual(len(result['evidence']['clock_observations'][0]['conflicting_values']),2)


if __name__=='__main__':
    unittest.main()
