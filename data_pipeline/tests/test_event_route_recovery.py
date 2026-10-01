"""General regressions for wrong calendar links and exhausted-search recovery."""
from datetime import date, datetime
from pathlib import Path
import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

from lxml import html
from data_pipeline.collectors.schedules.enricher import OfficialScheduleEnricher
from data_pipeline.collectors.schedules.event_routes import (
    issuer_listing_fallbacks, read_route_proof, scoped_candidates, fiscal_period,
)


class EventRouteRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.index = 'https://issuer.test/investors/events/'
        self.detail = self.index + 'event-details/2026/q3/'
        self.provider = 'https://provider.test/opaque/42'
        self.day = date(2026, 9, 29)
        self.call = dict(id=1, ticker='TEST', company_name='Example Company',
            ir_url=self.index, webcast_date=self.day, schedule_revision=1,
            verified_fiscal_year=2026, verified_fiscal_quarter='Q3')
        self.enricher = OfficialScheduleEnricher(api_key='')

    def run_pages(self, pages, **overrides):
        fetched = []
        def fetch(url):
            fetched.append(url)
            content = pages.get(url, '<html><p>Not found</p></html>')
            self.enricher._page_documents[url] = content
            self.enricher._page_fetch_succeeded = True
            return self.enricher._extract_page_details(content, url)
        with patch.object(self.enricher, '_fetch_event_page', side_effect=fetch), \
             patch.object(self.enricher, '_fetch_event_page_with_browser', return_value=('', None)), \
             patch.object(self.enricher, '_search_event_results', side_effect=AssertionError('search unavailable')), \
             patch('data_pipeline.collectors.schedules.enricher.database') as db:
            result = self.enricher.verify_call({**self.call, **overrides}, dry_run=True)
        db.update_verified_schedule_time.assert_not_called()
        db.update_official_schedule_discovery.assert_not_called()
        return result, fetched

    def index_dom(self, clock=''):
        return f'''<div><header><a href="/events/list/?eventDisplay=past">Past Events</a>
            <a href="/events/list/">Today</a></header>
            <article><h2><a href="{self.detail}">Third Quarter 2026 Earnings</a></h2>
            <p>September 29, 2026 {clock}</p></article></div>'''

    def detail_dom(self):
        return f'''<article><h1>Third Quarter 2026 Earnings Call</h1>
            <p>September 29, 2026 at 10:00 AM EDT</p>
            <a href="{self.provider}">Listen to webcast</a></article>'''

    def test_navigation_cannot_borrow_neighbouring_event_identity(self):
        links = scoped_candidates(html.fromstring(self.index_dom()), self.index)
        self.assertEqual([item['url'] for item in links], [self.detail])

    def test_explicit_reverse_quarter_notation_retains_issuer_identity(self):
        self.assertEqual(fiscal_period('Conference Call on 2026 3Q Earnings'), (2026, 'Q3'))
        self.assertEqual(fiscal_period('1Q FY2027 Earnings'), (2027, 'Q1'))
        self.assertEqual(fiscal_period('September 29, 2026'), (None, None))

    def test_follow_detail_and_keep_provider_even_when_index_has_exact_clock(self):
        result, fetched = self.run_pages({self.index: self.index_dom('earnings call at 10 AM EDT'),
                                         self.detail: self.detail_dom()})
        self.assertEqual(result.event_url, self.detail)
        self.assertEqual(result.webcast_url, self.provider)
        self.assertIn(self.detail, fetched)
        proof = read_route_proof(result.schedule_evidence)
        self.assertEqual(proof['event_url'], self.detail)
        self.assertEqual(proof['webcast_url'], self.provider)

    def test_correct_detail_does_not_depend_on_navigation_order_or_label(self):
        for label, path in [('Past Events', '/events/list/'), ('Today', '/events/today/'),
                            ('Events List View', '/events/list/?shortcode=x')]:
            with self.subTest(label=label):
                self.enricher = OfficialScheduleEnricher(api_key='')
                index = self.index_dom().replace('Past Events', label).replace(
                    '/events/list/?eventDisplay=past', path)
                result, _ = self.run_pages({self.index: index, self.detail: self.detail_dom()})
                self.assertEqual(result.webcast_url, self.provider)

    def test_issuer_detail_labelled_earnings_call_is_read_for_time_and_provider(self):
        index = self.index_dom().replace('Third Quarter 2026 Earnings</a>',
                                        'Third Quarter 2026 Earnings Call</a>')
        result, fetched = self.run_pages({self.index: index, self.detail: self.detail_dom()})
        self.assertEqual(result.event_url, self.detail)
        self.assertEqual(result.webcast_url, self.provider)
        self.assertIn(self.detail, fetched)

    def test_broken_detail_root_recovers_listing_without_search_or_stored_provider(self):
        broken = self.index + 'event-details/'
        result, fetched = self.run_pages({self.index: self.index_dom(), self.detail: self.detail_dom()},
                                        ir_url=broken)
        self.assertEqual(result.event_url, self.detail)
        self.assertEqual(result.webcast_url, self.provider)
        self.assertIn(self.index, fetched)
        self.assertIn({'reason': 'issuer_listing_recovery', 'url': self.index},
                      self.enricher.last_dry_run['route_diagnostics'])
        self.assertIn({'reason': 'replace_route_from_current_evidence',
                       'url': self.provider, 'retained_checked_at': ''},
                      self.enricher.last_dry_run['route_diagnostics'])

    def test_listing_recovery_never_adopts_wrong_quarter(self):
        index = self.index_dom().replace('Third Quarter', 'Second Quarter')
        result, _ = self.run_pages({self.index: index}, ir_url=self.index+'event-details/')
        self.assertIsNone(result)
        self.assertIsNone(self.enricher.last_dry_run['discovery'])

    def test_fallback_paths_are_bounded_same_origin_and_drop_query(self):
        self.assertEqual(issuer_listing_fallbacks(self.detail+'?redirect=https://evil.test'), [self.index])
        for value in ('https://issuer.test/', 'https://issuer.test/event-details/',
                      'https://issuer.test/elsewhere', 'javascript:alert(1)'):
            self.assertEqual(issuer_listing_fallbacks(value), [])

    def test_distinct_event_types_cannot_lend_provider_links(self):
        dom = '''<div><div><h2>Q3 FY2026 Earnings Call</h2><p>September 29, 2026</p></div>
          <div><h2>Investor Day</h2><a href="https://provider.test/wrong">Webcast</a></div></div>'''
        result, _ = self.run_pages({self.index: dom})
        self.assertIsNone(result)
        discovery = self.enricher.last_dry_run['discovery']
        self.assertIsNotNone(discovery)
        self.assertIsNone(discovery['webcast_url'])

    def test_target_time_and_provider_survive_unrelated_calendar_event(self):
        dom = self.detail_dom() + '''<article><h2>Investor Day</h2>
            <p>October 14, 2026 at 8:30 AM ET</p><a href="https://provider.test/other">Webcast</a></article>'''
        result, _ = self.run_pages({self.index: dom})
        self.assertEqual(result.scheduled_at_utc.hour, 14)
        self.assertEqual(result.webcast_url, self.provider)
        self.assertFalse(self.enricher.last_dry_run['conflicted'])

    def test_real_same_event_conflict_still_blocks_verification(self):
        result, _ = self.run_pages({self.index: self.index_dom('earnings call at 9 AM EDT'),
                                   self.detail: self.detail_dom()})
        self.assertIsNone(result)
        self.assertTrue(self.enricher.last_dry_run['conflicted'])


@unittest.skipUnless(os.getenv('RUN_LOCAL_BROWSER_SMOKE') == '1', 'requires local Chromium')
class ScheduleBrowserAccessStatusTest(unittest.TestCase):
    def test_http_denial_cannot_become_successful_page_or_clock_evidence(self):
        class Denied(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(403)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<article>Q3 FY2026 Earnings Call September 29, 2026 at 10 AM EDT</article>')
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Denied)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        e = OfficialScheduleEnricher(api_key='')
        try:
            result = asyncio.run(e._fetch_event_page_with_browser_async(
                f'http://127.0.0.1:{server.server_port}/event'))
            self.assertEqual(result, ('', None))
            self.assertFalse(e._page_fetch_succeeded)
            self.assertFalse(e._page_documents)
            with patch('data_pipeline.collectors.schedules.enricher.database') as db:
                e._record_unverified_outcome({'id': 1})
            self.assertEqual(db.record_schedule_enrichment_outcome.call_args.kwargs['failure_kind'],
                             'issuer_browser_access_denied')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
