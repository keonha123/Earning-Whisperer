"""Near-term exact-start enrichment: cheap HTTP, bounded render, durable proof."""
from datetime import date, datetime, timezone
import os
import unittest
from unittest import mock

import requests

from data_pipeline.application.schedules import ScheduleService
from data_pipeline.collectors.schedules.enricher import OfficialScheduleEnricher


class FixedDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return cls(2026, 9, 22, 12)


class NearbyBrowserTimeEnrichmentTest(unittest.TestCase):
    def setUp(self):
        self.enricher = OfficialScheduleEnricher(api_key='')
        self.issuer = 'https://ir.example.com/events'
        self.detail = 'https://ir.example.com/events/q4'
        self.provider = 'https://events.provider.test/earnings/123'
        self.call = dict(id=7, ticker='EX', company_name='Example Inc.',
                         earning_at=date(2026, 9, 23), ir_url=self.issuer,
                         event_url=self.detail, schedule_revision=4)
        self.http, self.rendered, self.requests, self.renders = {}, {}, [], []
        self.stack = __import__('contextlib').ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch('data_pipeline.collectors.schedules.enricher.datetime', FixedDatetime))
        self.stack.enter_context(mock.patch.dict(os.environ, {
            'SCHEDULE_TIME_BROWSER_DAYS_AHEAD': '2', 'SCHEDULE_TIME_BROWSER_PAGES_PER_CALL': '2',
            'SCHEDULE_TIME_BROWSER_PAGES_PER_REFRESH': '6', 'SCHEDULE_TIME_BROWSER_SECONDS_PER_CALL': '60',
            'SCHEDULE_TIME_BROWSER_SECONDS_PER_REFRESH': '120'}, clear=False))
        self.stack.enter_context(mock.patch('data_pipeline.collectors.schedules.enricher.requests.get', side_effect=self.fetch))
        self.stack.enter_context(mock.patch.object(self.enricher, '_fetch_event_page_with_browser_async', side_effect=self.render))
        self.stack.enter_context(mock.patch.object(self.enricher, '_search_event_results', return_value=[]))
        self.db = self.stack.enter_context(mock.patch('data_pipeline.collectors.schedules.enricher.database'))
        self.db.update_verified_schedule_time.return_value = 5

    def card(self, clock='', *, day='September 23, 2026', title='Example Q4 2026 earnings call', link=True):
        return ('<article><h2>' + title + '</h2><p>' + day + clock + '</p>' +
                (f'<a href="{self.provider}">Webcast</a>' if link else '') + '</article>')

    def fetch(self, url, **kwargs):
        self.requests.append(url)
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response.headers['Content-Type'] = 'text/html'
        response._content = self.http.get(url, '<html><body></body></html>').encode()
        return response

    async def render(self, url):
        self.renders.append(url)
        content = self.rendered.get(url, '<html><body></body></html>')
        self.enricher._page_documents[url] = content
        self.enricher._page_fetch_succeeded = True
        return self.enricher._extract_page_details(content, url)

    def test_corroborated_http_clocks_avoid_browser_even_other_known_page_has_no_time(self):
        self.http[self.detail] = self.card(' at 9 a.m. ET')
        self.http[self.issuer] = self.card()
        self.http[self.provider] = self.card(' at 1 p.m. GMT',link=False)
        result = self.enricher.verify_call(self.call)
        self.assertEqual(result.scheduled_at_utc, datetime(2026, 9, 23, 13, tzinfo=timezone.utc))
        self.assertFalse(self.renders)
        self.assertIn(self.provider, self.requests)
        values = self.db.update_verified_schedule_time.call_args.args[1]
        self.assertEqual(values['expected_revision'], 4)
        self.assertEqual(values['observed_at'], FixedDatetime.utcnow())

    def test_dynamic_issuer_time_is_saved_with_utc_and_source(self):
        self.http[self.detail] = '<div id="event"></div>'
        self.rendered[self.detail] = self.card(' at 9 a.m. EDT')
        result = self.enricher.verify_call(self.call)
        self.assertEqual(result.scheduled_at_utc.hour, 13)
        self.assertEqual(result.source_timezone, 'EDT')
        self.assertTrue(result.schedule_source.endswith('_browser'))
        self.assertEqual(self.renders, [self.detail,self.provider])
        self.assertEqual(self.requests.count(self.detail), 1)
        self.db.update_verified_schedule_time.assert_called_once()

    def test_far_date_remains_http_only(self):
        self.call['earning_at'] = date(2026, 10, 5)
        self.http[self.detail] = self.card(day='October 5, 2026')
        self.rendered[self.detail] = self.card(' at 9 a.m. ET', day='October 5, 2026')
        self.assertIsNone(self.enricher.verify_call(self.call))
        self.assertEqual(self.renders, [])
        self.assertIn('outside_nearby_window', self.enricher.last_dry_run['browser_skipped'])
        self.db.update_verified_schedule_time.assert_not_called()

    def test_fresh_issuer_link_allows_provider_http_clock_without_browser(self):
        self.http[self.detail] = self.card()
        self.http[self.provider] = self.card(' at 9 a.m. EDT', link=False)
        result = self.enricher.verify_call(self.call)
        self.assertEqual(result.schedule_source, 'official_ir_linked_provider_http')
        self.assertEqual(result.event_url, self.detail)
        self.assertEqual(result.webcast_url, self.provider)
        self.assertFalse(self.renders)
        self.assertIn('issuer-route-v2:', result.schedule_evidence)

    def test_provider_dynamic_clock_preserves_issuer_identity(self):
        self.http[self.detail] = self.card()
        self.rendered[self.detail] = self.card()
        self.rendered[self.provider] = self.card(' at 9 a.m. EDT', link=False)
        result = self.enricher.verify_call(self.call)
        self.assertEqual(result.schedule_source, 'official_ir_linked_provider_browser')
        self.assertEqual(result.event_url, self.detail)
        self.assertEqual(self.renders, [self.detail, self.provider])
        self.assertEqual(self.requests.count(self.provider), 1)

    def test_unproven_stored_provider_is_never_read(self):
        self.call['webcast_url'] = self.provider
        self.assertIsNone(self.enricher.verify_call(self.call))
        self.assertNotIn(self.provider, self.requests + self.renders)

    def test_provider_wrong_issuer_date_and_quarter_are_rejected(self):
        for body in (self.card(' at 9 a.m. EDT', title='Other Q4 2026 earnings call'),
                     self.card(' at 9 a.m. EDT', day='September 24, 2026'),
                     self.card(' at 9 a.m. EDT', title='Example Q3 2026 earnings call')):
            with self.subTest(body=body):
                self.http[self.detail] = self.card()
                self.http[self.provider] = body
                self.assertIsNone(self.enricher.verify_call(self.call))
        self.db.update_verified_schedule_time.assert_not_called()

    def test_release_and_prepared_remarks_do_not_replace_live_qa_time(self):
        self.rendered[self.detail] = '''<article><h2>Example Q1 2027 earnings webcast</h2>
            <p>September 23, 2026. Prepared remarks webcast September 23, 2026 at 7 a.m. ET;
            Live Q&amp;A session September 23, 2026 at 8:30 a.m. ET.</p></article>'''
        result = self.enricher.verify_call(self.call)
        self.assertEqual(result.scheduled_at_utc.hour, 12)
        self.assertEqual(result.scheduled_at_utc.minute, 30)

    def test_changed_time_rechecks_fresh_documents_and_keeps_revision_guard(self):
        self.http[self.detail] = self.card(' at 9 a.m. ET')
        first = self.enricher.verify_call(self.call)
        self.http[self.detail] = self.card(' at 10 a.m. ET')
        second = self.enricher.verify_call({**self.call, 'schedule_revision': 5})
        self.assertNotEqual(first.scheduled_at_utc, second.scheduled_at_utc)
        self.assertEqual(second.scheduled_at_utc.hour, 14)
        self.assertEqual(self.requests.count(self.detail), 2)
        self.assertEqual(self.db.update_verified_schedule_time.call_args.args[1]['expected_revision'], 5)

    def test_provider_or_capture_browser_time_not_withdrawn_from_clockless_ir_card(self):
        self.http[self.detail] = self.card()
        for source in ('official_browser_event', 'official_browser_provider', 'official_ir_linked_provider_browser', 'official_ir_event_browser'):
            self.enricher.verify_call({**self.call, 'scheduled_at_utc': datetime(2026, 9, 23, 13),
                                      'schedule_source': source})
            self.assertFalse(self.enricher.last_dry_run['official_time_withdrawn'])

    def test_browser_page_budget_is_shared_across_calls(self):
        with mock.patch.dict(os.environ, {'SCHEDULE_TIME_BROWSER_PAGES_PER_REFRESH': '2'}):
            self.enricher.verify_call(self.call)
            self.enricher.verify_call({**self.call, 'id': 8, 'ticker': 'NEXT'})
        self.assertEqual(len(self.renders), 2)
        self.assertIn('browser_budget_exhausted', self.enricher.last_dry_run['browser_skipped'])

    def test_batch_health_reports_provenance_and_browser_cost(self):
        self.http[self.detail] = self.card(' at 9 a.m. ET')
        self.http[self.provider] = self.card(' at 1 p.m. GMT',link=False)
        repository, health = mock.Mock(), mock.Mock()
        repository.get_calls_missing_verified_time.return_value = [self.call]
        ScheduleService(repository, health, schedule_chain=mock.Mock(),
                        enricher_factory=lambda: self.enricher).enrich_schedule_times()
        values = health.record_event.call_args.kwargs
        self.assertEqual(values['status'], 'verified')
        self.assertEqual(values['scheduled_at_utc'], '2026-09-23T13:00:00+00:00')
        self.assertEqual(values['browser_pages'], 0)

    def test_issuer_clock_cannot_hide_same_event_provider_disagreement(self):
        self.http[self.detail] = self.card(' at 2:00 PM PST')
        self.http[self.provider] = self.card(' at 9:00 PM GMT',link=False)
        self.assertIsNone(self.enricher.verify_call(self.call))
        self.db.update_verified_schedule_time.assert_not_called()
        outcome=self.db.record_schedule_enrichment_outcome.call_args.kwargs
        self.assertEqual(outcome['failure_kind'],'ambiguous_call_time')
        self.assertEqual(outcome['route_observation']['webcast_url'],self.provider)
        observations=outcome['clock_observations']
        self.assertEqual({x['value'] for x in observations},{'2026-09-23T21:00:00+00:00','2026-09-23T22:00:00+00:00'})
        self.assertEqual({x['source'] for x in observations},{self.detail,self.provider})

    def test_rendered_provider_clock_is_checked_even_after_issuer_http_clock(self):
        self.http[self.detail] = self.card(' at 2:00 PM PST')
        self.rendered[self.provider] = self.card(' at 9:00 PM GMT',link=False)
        self.assertIsNone(self.enricher.verify_call(self.call))
        self.assertEqual(self.renders,[self.provider])
        self.assertEqual(self.db.record_schedule_enrichment_outcome.call_args.kwargs['failure_kind'],'ambiguous_call_time')

    def test_legal_company_suffix_does_not_drop_provider_identity_before_clock_comparison(self):
        self.call['company_name']='Nike Inc.'
        title='Q1 FY27 NIKE Inc. Earnings Call'
        self.http[self.detail]=self.card(' at 2:00 PM PST',title=title)
        self.http[self.provider]=self.card(' at 9:00 PM GMT',title=title,link=False)
        self.assertIsNone(self.enricher.verify_call(self.call))
        self.assertEqual(self.db.record_schedule_enrichment_outcome.call_args.kwargs['failure_kind'],'ambiguous_call_time')

    def test_region_timezone_and_explicit_provider_clock_agree_without_reinterpreting_pst(self):
        self.http[self.detail] = self.card(' at 2:00 PM PT')
        self.http[self.provider] = self.card(' at 9:00 PM GMT',link=False)
        result=self.enricher.verify_call(self.call)
        self.assertEqual(result.scheduled_at_utc,datetime(2026,9,23,21,tzinfo=timezone.utc))
        self.assertFalse(self.enricher.last_dry_run['conflicted'])

    def test_provider_failure_cannot_clear_previously_observed_clock_conflict(self):
        import json
        self.http[self.detail] = self.card(' at 2:00 PM PST')
        self.http[self.provider] = self.card(' at 9:00 PM GMT',link=False)
        self.enricher.verify_call(self.call)
        clocks=self.db.record_schedule_enrichment_outcome.call_args.kwargs['clock_observations']
        self.http[self.provider]='<html></html>'
        call={**self.call,'schedule_revalidation_reason':'ambiguous_call_time',
              'schedule_revalidation_evidence':json.dumps({'route_identity_verified':True,'clock_observations':clocks})}
        self.assertIsNone(self.enricher.verify_call(call))
        self.assertIn('prior_source_clock_conflict_unresolved',str(self.enricher.last_dry_run['route_diagnostics']))
        self.db.update_verified_schedule_time.assert_not_called()
        self.http[self.provider]=self.card(' at 10:00 PM GMT',link=False)
        result=self.enricher.verify_call(call)
        self.assertEqual(result.scheduled_at_utc.hour,22)
        self.assertFalse(self.enricher.last_dry_run['conflicted'])

    def test_issuer_failure_cannot_clear_previously_observed_clock_conflict_from_provider_alone(self):
        import json
        self.http[self.detail] = self.card(' at 2:00 PM PST')
        self.http[self.provider] = self.card(' at 9:00 PM GMT', link=False)
        self.assertIsNone(self.enricher.verify_call(self.call))
        clocks = self.db.record_schedule_enrichment_outcome.call_args.kwargs['clock_observations']
        call = {**self.call, 'schedule_revalidation_reason': 'ambiguous_call_time',
                'schedule_revalidation_evidence': json.dumps({
                    'route_identity_verified': True, 'clock_observations': clocks})}
        # The listing still authenticates the event/provider, while the exact
        # issuer page whose printed clock disagreed is temporarily unavailable.
        self.http[self.issuer] = self.card()
        self.http[self.detail] = '<html></html>'
        def issuer_denied(url, **kwargs):
            response = self.fetch(url, **kwargs)
            if url == self.detail:
                response.status_code = 403
            return response
        with mock.patch('data_pipeline.collectors.schedules.enricher.requests.get', side_effect=issuer_denied):
            self.assertIsNone(self.enricher.verify_call(call))
        self.db.update_verified_schedule_time.assert_not_called()
        self.assertEqual(self.db.record_schedule_enrichment_outcome.call_args.kwargs['failure_kind'],
                         'ambiguous_call_time')
        # Removing only the clock is also not evidence of agreement.
        self.http[self.detail] = self.card()
        self.assertIsNone(self.enricher.verify_call(call))
        self.db.update_verified_schedule_time.assert_not_called()
        # Re-observing both exact sources with matching times does resolve it.
        self.http[self.detail] = self.card(' at 2:00 PM PT')
        result = self.enricher.verify_call(call)
        self.assertEqual(result.scheduled_at_utc.hour, 21)
        self.assertFalse(self.enricher.last_dry_run['conflicted'])

    def test_proven_provider_is_crosschecked_before_issuer_outage_exhausts_two_page_budget(self):
        self.http[self.detail] = self.card(' at 9 a.m. ET')
        self.http[self.provider] = self.card(' at 1 p.m. GMT', link=False)
        self.assertIsNotNone(self.enricher.verify_call(self.call))
        saved = self.db.update_verified_schedule_time.call_args.args[1]
        call = {**self.call, **saved, 'schedule_discovery_checked_at': FixedDatetime.utcnow()}
        self.db.update_verified_schedule_time.reset_mock()
        self.http.clear()
        self.rendered[self.provider] = self.card(' at 2 p.m. GMT', link=False)
        def issuer_denied(url, **kwargs):
            response = self.fetch(url, **kwargs)
            if url != self.provider:
                response.status_code = 403
            return response
        with mock.patch('data_pipeline.collectors.schedules.enricher.requests.get', side_effect=issuer_denied):
            self.assertIsNone(self.enricher.verify_call(call))
        self.assertEqual(self.renders[0], self.provider)
        self.assertLessEqual(len(self.renders), 2)
        self.db.update_verified_schedule_time.assert_not_called()
        outcome = self.db.record_schedule_enrichment_outcome.call_args.kwargs
        self.assertEqual(outcome['failure_kind'], 'ambiguous_call_time')
        self.assertNotIn('route_observation', outcome)


@unittest.skipUnless(os.getenv('RUN_SCHEDULE_BROWSER_SMOKE') == '1',
                     'Requires installed Chromium and loopback sockets')
class NearbyRenderedTimeSmokeTest(unittest.TestCase):
    def test_real_browser_reads_delayed_live_qa_clock_once_without_playing_media(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        requested = []
        page = '''<html><body><div id="events"></div>
            <audio autoplay src="/must-not-fetch.wav"></audio>
            <script>setTimeout(() => {
              document.getElementById('events').innerHTML = `<article>
                <h2>Example Q1 FY2027 earnings webcast</h2>
                <p>September 23, 2026. Prepared remarks webcast September 23, 2026 at 7 a.m. ET;
                Live Q&amp;A session September 23, 2026 at 10 a.m. ET.</p>
                <form action="/must-not-register"><input name="email"><button>Register</button></form>
                </article>`;
            }, 2500);</script></body></html>'''

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requested.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(page.encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/event'
            enricher = OfficialScheduleEnricher(api_key='')
            call = dict(id=77, ticker='EX', company_name='Example', ir_url=url,
                        event_url=url, earning_at=date(2026, 9, 23), schedule_revision=2)
            with mock.patch('data_pipeline.collectors.schedules.enricher.datetime', FixedDatetime), \
                    mock.patch('data_pipeline.collectors.schedules.enricher.database') as db, \
                    mock.patch.object(enricher, '_search_event_results', return_value=[]):
                db.update_verified_schedule_time.return_value = 3
                verified = enricher.verify_call(call)
            self.assertIsNotNone(verified)
            self.assertEqual(verified.scheduled_at_utc.isoformat(), '2026-09-23T14:00:00+00:00')
            self.assertEqual(enricher.last_dry_run['browser_pages'], 1)
            self.assertEqual(requested.count('/event'), 2)  # One HTTP + one browser navigation.
            self.assertNotIn('/must-not-fetch.wav', requested)
            self.assertNotIn('/must-not-register', requested)
            values = db.update_verified_schedule_time.call_args.args[1]
            self.assertEqual(values['scheduled_at_utc'], datetime(2026, 9, 23, 14))
            self.assertEqual(values['expected_revision'], 2)
            self.assertTrue(values['schedule_source'].endswith('_browser'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
