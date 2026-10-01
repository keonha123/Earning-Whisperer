"""CCL's sequential partial-fetch failure, using real saved issuer HTML and SQL."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from unittest import TestCase, mock
from sqlalchemy import text
from data_pipeline.collectors.schedules import enricher as module
from data_pipeline.collectors.schedules.event_routes import route_proof
from data_pipeline.collectors.schedules.route_retention import retained_route_fields
from data_pipeline.storage import schedules, schema
from data_pipeline.tests.test_schedule_revision_storage import SQLiteScheduleEngine

DETAIL = 'https://www.carnivalcorp.com/event/third-quarter-2026-earnings/'
INDEX = 'https://www.carnivalcorp.com/investors/'
PROVIDER = 'https://event.choruscall.com/mediaframe/webcast.html?webcastid=lE7HpeUW'
DAY = date(2026, 9, 29)
FIXTURES = Path(__file__).parent / 'fixtures' / 'schedules'

class ScheduleEvidenceRetentionTest(TestCase):
    def setUp(self):
        self.engine = SQLiteScheduleEngine()
        self.addCleanup(self.engine.raw.dispose)
        self.now = datetime(2026, 9, 29, 13, 4)
        class Clock(datetime):
            @classmethod
            def utcnow(cls):
                return self.now
            @classmethod
            def now(cls, tz=None):
                return self.now.replace(tzinfo=timezone.utc).astimezone(tz) if tz else self.now
        for target, attr, value in ((schedules.connection, 'engine', self.engine),
                                    (schema, 'ensure_schedule_time_schema', lambda: None),
                                    (module, 'datetime', Clock)):
            patch = mock.patch.object(target, attr, value); patch.start(); self.addCleanup(patch.stop)
        with self.engine.raw.begin() as conn:
            conn.execute(text("INSERT INTO calls(id,ticker,earning_at,webcast_date,schedule_revision,event_url) VALUES(1,'CCL',:day,:day,0,:detail)"), {'day': DAY, 'detail': DETAIL})
            conn.execute(text("INSERT INTO stocks(ticker,company_name,ir_url) VALUES('CCL','Carnival Corporation',:url)"), {'url':INDEX})
        self.enricher = module.OfficialScheduleEnricher(api_key='')
        self.enricher._nearby_browser_allowed = lambda: False
        self.pages = {DETAIL: (FIXTURES/'ccl-event-20260930.html').read_text(),
                      INDEX: (FIXTURES/'ccl-ir-20260930.html').read_text()}

    def row(self):
        with self.engine.raw.connect() as conn:
            return dict(conn.execute(text('SELECT * FROM calls WHERE id=1')).mappings().one())

    def update(self, **values):
        with self.engine.raw.begin() as conn:
            conn.execute(text('UPDATE calls SET '+','.join(key+'=:'+key for key in values)+' WHERE id=1'), values)

    def run_pages(self, pages=None, call=None):
        pages = self.pages if pages is None else pages
        def fetch(url):
            content = pages.get(url, '')
            if content is None:
                self.enricher._record_issuer_failure('issuer_http_timeout','Timeout fixture', retry_env='TEST_RETRY',retry_default=1)
                return '', None
            self.enricher._page_documents[url] = content
            self.enricher._page_fetch_succeeded = True
            return self.enricher._extract_page_details(content,url)
        call = dict(call) if call is not None else {**self.row(), 'ir_url': INDEX, 'company_name': 'Carnival Corporation',
                'schedule_enrichment_retry_not_before': None}
        with mock.patch.object(self.enricher,'_fetch_event_page',side_effect=fetch), \
             mock.patch.object(self.enricher,'_search_event_results',return_value=[]):
            return self.enricher.verify_call(call)

    def weak_index(self, clock='10:00'):
        return ('<html><body><script type="application/ld+json">'+json.dumps({'@type':'Event',
            'name':'Third Quarter 2026 Earnings Conference Call', 'startDate':f'2026-09-29T{clock}:00-04:00'})+
            '</script><article><h2>Third Quarter 2026 Earnings</h2><p>September 29, 2026</p>'+
            f'<a href="{DETAIL}">Event details</a></article></body></html>')

    def test_real_ccl_good_partial_timeout_and_recovery_preserve_route_without_ttl_extension(self):
        self.assertIsNotNone(self.run_pages())
        good = self.row()
        self.assertEqual(good['webcast_url'], PROVIDER)
        self.assertEqual(good['scheduled_at_utc'], '2026-09-29 14:00:00')
        self.assertFalse(self.enricher.last_dry_run['conflicted'])
        self.now += timedelta(minutes=10)
        self.assertIsNotNone(self.run_pages({DETAIL: None, INDEX:self.weak_index()}))
        partial = self.row()
        for key in ('webcast_url','event_url','schedule_discovery_fingerprint','schedule_discovery_checked_at','schedule_evidence'):
            self.assertEqual(partial[key],good[key],key)
        self.assertEqual(partial['time_verified_at'], str(self.now))
        self.assertIn('retain_previous_route_missing_provider',str(self.enricher.last_dry_run['route_diagnostics']))
        self.now += timedelta(minutes=10)
        self.assertIsNotNone(self.run_pages())
        recovered=self.row()
        self.assertEqual(recovered['webcast_url'], PROVIDER)
        self.assertEqual(recovered['scheduled_at_utc'], '2026-09-29 14:00:00')
        self.assertEqual(recovered['webcast_date'], '2026-09-29')
        self.assertEqual(recovered['schedule_discovery_checked_at'],str(self.now))
        self.assertFalse(self.enricher.last_dry_run['conflicted'])

    def test_clock_only_conflict_keeps_fresh_route_atomically(self):
        self.run_pages(); self.now += timedelta(minutes=10)
        index = '<article><h2>Q3 2026 Earnings Call</h2><p>September 29, 2026 at 11:00 AM EDT</p></article>'
        self.assertIsNone(self.run_pages({**self.pages, INDEX:index}))
        row=self.row()
        self.assertIsNone(row['scheduled_at_utc'])
        self.assertEqual(row['webcast_url'],PROVIDER)
        self.assertEqual(row['schedule_revalidation_reason'],'ambiguous_call_time')
        evidence=json.loads(row['schedule_revalidation_evidence'])
        self.assertEqual(evidence['conflict_kind'],'start_time_conflict')
        self.assertTrue(evidence['route_identity_verified'])
        self.assertEqual(evidence['route_action'],'observed')
        self.assertEqual(row['schedule_discovery_checked_at'],str(self.now))
        self.assertTrue(row['schedule_discovery_fingerprint'])

    def test_actual_event_date_conflict_never_authenticates_route(self):
        self.run_pages(); self.now += timedelta(minutes=10)
        index = '<article><h2>Q3 2026 Earnings Call</h2><p>September 30, 2026 at 10:00 AM EDT</p><a href="https://video.test/wrong">Webcast</a></article>'
        self.assertIsNone(self.run_pages({**self.pages, INDEX:index}))
        row=self.row()
        self.assertEqual(row['schedule_revalidation_reason'],'ambiguous_event_identity')
        self.assertNotEqual(row['webcast_url'],'https://video.test/wrong')
        self.assertIsNone(row['schedule_discovery_fingerprint'])
        self.assertNotIn('route_identity_verified', row['schedule_revalidation_evidence'] or '')

    def test_cancellation_withdraws_clock_and_reusable_proof(self):
        self.run_pages(); self.now += timedelta(minutes=10)
        cancelled='<article><h2>Q3 2026 Earnings Call</h2><p>September 29, 2026 cancelled.</p></article>'
        self.assertIsNone(self.run_pages({DETAIL:cancelled,INDEX:''}))
        row=self.row()
        self.assertIsNone(row['scheduled_at_utc'])
        self.assertEqual(row['schedule_revalidation_status'],'cancelled')
        self.assertIsNone(row['schedule_discovery_fingerprint'])

    def test_cas_and_active_rows_protect_both_components(self):
        self.run_pages(); good=self.row(); self.now += timedelta(minutes=10)
        payload=dict(webcast_date=DAY,scheduled_at_utc=datetime(2026,9,29,15),event_url=DETAIL,
            webcast_url=None,schedule_evidence='same event weak observation',observed_at=self.now,
            expected_revision=good['schedule_revision']-1)
        self.assertIsNone(schedules.update_verified_schedule_time(1,payload))
        for fields in ({'stream_probe_status':'probing'}, {'status':'running'},
                       {'status':'completed'}, {'capture_lease_owner':'worker'},
                       {'capture_lease_until': datetime.utcnow()+timedelta(minutes=5)}):
            self.update(**good);self.update(**fields)
            self.assertIsNone(schedules.update_verified_schedule_time(1,{**payload,'expected_revision':good['schedule_revision']}))
            self.assertEqual(self.row()['webcast_url'],PROVIDER)
            self.assertEqual(self.row()['scheduled_at_utc'],good['scheduled_at_utc'])

    def test_old_proof_timestamp_is_never_refreshed_by_missing_provider(self):
        self.run_pages();good=self.row();self.now += timedelta(hours=7)
        self.assertIsNotNone(self.run_pages({DETAIL:None,INDEX:self.weak_index()}))
        row=self.row()
        self.assertEqual(row['schedule_discovery_checked_at'],good['schedule_discovery_checked_at'])
        self.assertEqual(row['schedule_evidence'],good['schedule_evidence'])

    def test_retention_rejects_unproven_different_day_and_kind(self):
        self.run_pages();good=self.row()
        changes={'webcast_date':DAY,'event_url':DETAIL,'webcast_url':None}
        self.assertTrue(retained_route_fields(good,changes))
        self.assertFalse(retained_route_fields(good,{**changes,'webcast_date':date(2026,9,30)}))
        self.assertFalse(retained_route_fields(good,{**changes,'schedule_evidence':'Post-Earnings Analyst Call'}))
        self.assertFalse(retained_route_fields({**good,'schedule_discovery_fingerprint':None},changes))


    def test_clock_then_identity_conflict_revokes_proof_even_when_clock_already_null(self):
        self.run_pages(); self.now += timedelta(minutes=10)
        clock_conflict='<article><h2>Q3 2026 Earnings Call</h2><p>September 29, 2026 at 11:00 AM EDT</p></article>'
        self.run_pages({**self.pages, INDEX:clock_conflict})
        clock_row=self.row()
        self.assertTrue(clock_row['schedule_discovery_fingerprint'])
        self.assertIsNone(clock_row['scheduled_at_utc'])
        self.now += timedelta(minutes=10)
        other_day='<article><h2>Q3 2026 Earnings Call</h2><p>September 30, 2026 at 10:00 AM EDT</p><a href="https://video.test/wrong">Webcast</a></article>'
        self.run_pages({**self.pages, INDEX:other_day})
        revoked=self.row()
        self.assertEqual(revoked['schedule_revalidation_reason'],'ambiguous_event_identity')
        self.assertGreater(revoked['schedule_revision'], clock_row['schedule_revision'])
        for field in ('schedule_discovery_fingerprint','schedule_discovery_checked_at','schedule_revalidation_evidence'):
            self.assertIsNone(revoked[field],field)
        self.now += timedelta(minutes=10)
        schedules.record_schedule_enrichment_outcome(1,failure_kind='ambiguous_call_time',
            error='Clock-only later, no new route',retry_minutes=30,
            expected_revision=revoked['schedule_revision'],observed_at=self.now)
        for field in ('schedule_discovery_fingerprint','schedule_discovery_checked_at','schedule_revalidation_evidence'):
            self.assertIsNone(self.row()[field],field)

    def test_cancel_postpone_tbd_override_simultaneous_clock_conflict(self):
        self.run_pages(); good=self.row()
        for status, wording in (('cancelled','cancelled'),('postponed','postponed'),('time_tbd','time to be determined')):
            with self.subTest(status=status):
                self.update(**good); self.now += timedelta(minutes=10)
                page=f'<article><h2>Q3 2026 Earnings Call</h2><p>Earnings call September 29, 2026 at 10:00 AM ET.</p><p>Earnings call September 29, 2026 at 11:00 AM ET.</p><p>Earnings call September 29, 2026 {wording}.</p></article>'
                self.assertIsNone(self.run_pages({DETAIL:page,INDEX:''}))
                row=self.row()
                self.assertIn(status,self.enricher.last_dry_run['unavailable_statuses'])
                self.assertEqual(row['schedule_revalidation_reason'],'official_'+status)
                self.assertIsNone(row['scheduled_at_utc'])
                self.assertIsNone(row['schedule_discovery_fingerprint'])
                self.assertIsNone(row['schedule_discovery_checked_at'])
                self.assertIsNone(row['schedule_revalidation_evidence'])


    def test_json_only_clock_on_other_date_cannot_receive_clock_only_marker(self):
        self.run_pages(); good=self.row()
        for starts in (['2026-09-30T10:00:00-04:00'],
                       ['2026-09-30T10:00:00-04:00','2026-09-30T11:00:00-04:00']):
            with self.subTest(starts=starts):
                self.update(**good); self.now += timedelta(minutes=10)
                page='<html><body>'+''.join('<script type="application/ld+json">'+json.dumps({
                    '@type':'Event','name':'Third Quarter 2026 Earnings Conference Call',
                    'startDate':start})+'</script>' for start in starts)+'</body></html>'
                self.assertIsNone(self.run_pages({**self.pages,INDEX:page}))
                row=self.row()
                self.assertEqual(row['schedule_revalidation_reason'],'ambiguous_event_identity')
                self.assertIsNone(row['schedule_discovery_fingerprint'])
                self.assertIsNone(row['schedule_revalidation_evidence'])

    def test_other_page_unavailability_wins_over_clock_conflict(self):
        self.run_pages(); good=self.row()
        for status in ('cancelled','postponed'):
            with self.subTest(status=status):
                self.update(**good); self.now += timedelta(minutes=10)
                clock_page='<article><h2>Q3 2026 Earnings Call</h2><p>Earnings call September 29, 2026 at 10:00 AM ET.</p><p>Earnings call September 29, 2026 at 11:00 AM ET.</p></article>'
                unavailable=f'<article><h2>Q3 2026 Earnings Call</h2><p>Earnings call September 29, 2026 {status}.</p></article>'
                self.assertIsNone(self.run_pages({DETAIL:clock_page,INDEX:unavailable}))
                self.assertEqual(self.row()['schedule_revalidation_reason'],'official_'+status)
                self.assertIsNone(self.row()['schedule_discovery_fingerprint'])
                self.assertIsNone(self.row()['schedule_revalidation_evidence'])


    def test_repository_projection_carries_original_route_proof_into_regular_enrichment(self):
        self.assertIsNotNone(self.run_pages())
        good=self.row(); self.now += timedelta(minutes=11)
        candidates=schedules.get_calls_missing_verified_time(limit=10,days_ahead=2,
            reference_time_utc=self.now.replace(tzinfo=timezone.utc))
        self.assertEqual(len(candidates),1)
        call=candidates[0]
        self.assertEqual(call['schedule_discovery_fingerprint'],good['schedule_discovery_fingerprint'])
        self.assertEqual(call['schedule_discovery_checked_at'],good['schedule_discovery_checked_at'])
        self.assertIsNotNone(self.run_pages({DETAIL:None,INDEX:self.weak_index()},call=call))
        self.assertIn('retain_previous_route_missing_provider',str(self.enricher.last_dry_run['route_diagnostics']))
        self.assertEqual(self.row()['webcast_url'],PROVIDER)
        self.assertEqual(self.row()['schedule_discovery_checked_at'],good['schedule_discovery_checked_at'])
