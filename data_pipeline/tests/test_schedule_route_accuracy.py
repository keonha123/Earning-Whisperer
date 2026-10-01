"""Actual DOM candidates and complete enrichment decisions, without external state."""
from datetime import date, datetime
from pathlib import Path
import unittest
from unittest import mock
from data_pipeline.collectors.schedules.enricher import OfficialScheduleEnricher
from data_pipeline.collectors.schedules.event_routes import normalize_route, read_route_proof, fiscal_period


class RouteClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 18, 2, 0, tzinfo=tz)

    @classmethod
    def utcnow(cls):
        return cls(2026, 9, 17, 17, 0)


class ScheduleRouteAccuracyTest(unittest.TestCase):
    def setUp(self):
        clock = mock.patch('data_pipeline.collectors.schedules.enricher.datetime', RouteClock)
        clock.start()
        self.addCleanup(clock.stop)
        self.enricher = OfficialScheduleEnricher(api_key='')
        self.url = 'https://ir.example.com/events'
        self.day = date(2026,9,24)
        self.call = {'id':7,'ticker':'TEST','company_name':'Test Inc','ir_url':self.url,
                     'webcast_date':self.day,'schedule_revision':0}

    def discover(self, html, **call):
        self.enricher._page_documents[self.url] = html
        return self.enricher._discover_cached_event({**self.call,**call},self.url,self.day,'official_ir_page')

    def test_ad_iframe_cannot_outrank_real_webcast_or_receive_proof(self):
        found = self.discover('''<article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026</p>
            <a href="https://unlisted-video.test/42">Listen to webcast</a>
            <iframe src="https://ad.doubleclick.net/webcast?earnings=2026-09-24"></iframe></article>''')
        self.assertEqual(found.webcast_url,'https://unlisted-video.test/42')
        proof=read_route_proof(found.evidence)
        self.assertEqual(proof['webcast_url'],found.webcast_url)
        self.assertEqual(proof['relation'],'same_event_container')
        self.assertNotIn('doubleclick',found.evidence)

    def test_static_assets_never_playback_even_with_earnings_label(self):
        for extension in ('pdf','ics','webp','avif','svg','pptx'):
            with self.subTest(extension=extension):
                found=self.discover(f'''<article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026</p>
                    <a href="https://cdn.test/earnings-webcast.{extension}">Watch earnings presentation</a></article>''')
                self.assertIsNone(found.webcast_url)
                self.assertIsNone(read_route_proof(found.evidence)['webcast_url'])

    def test_unrelated_date_cannot_authenticate_old_webcast(self):
        found=self.discover('''<div><article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026</p></article>
            <article><h2>Prior conference call</h2><a href="https://video.test/old">Watch webcast</a></article></div>''')
        self.assertIsNotNone(found)
        self.assertIsNone(found.webcast_url)

    def test_parent_with_multiple_cards_cannot_lend_current_date(self):
        found=self.discover('''<div><div><h3>Q4 FY2026 Earnings Call</h3><p>September 24, 2026</p></div>
            <div><h3>Q3 FY2026 Earnings Call</h3><a href="https://video.test/old">Webcast</a></div></div>''')
        self.assertIsNone(found.webcast_url)

    def test_query_keywords_and_raw_javascript_are_not_link_proof(self):
        found=self.discover('''<article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026</p>
          <a href="https://external.test/?webcast=1&amp;date=2026-09-24">Learn more</a>
          <script>var x="https://external.test/earnings-webcast";</script></article>''')
        self.assertIsNone(found.webcast_url)

    def test_unknown_provider_allowed_when_issuer_directly_labels_link(self):
        found=self.discover('''<article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026</p>
          <a href="/event/q4-2026">Event details</a><a data-webcast-url="https://new-provider.test/id/opaque">Attend</a></article>''')
        self.assertEqual(found.event_url,'https://ir.example.com/event/q4-2026')
        self.assertEqual(found.webcast_url,'https://new-provider.test/id/opaque')
        self.assertEqual(found.event_identity['fiscal_quarter'],'Q4')

    def test_wrong_verified_fiscal_quarter_is_rejected_even_same_date(self):
        found=self.discover('''<article><h2>Q3 FY2026 Earnings Call</h2><p>September 24, 2026</p>
          <a href="https://video.test/old">Webcast</a></article>''',verified_fiscal_year=2026,verified_fiscal_quarter='Q4')
        self.assertIsNone(found)

    def test_legacy_calendar_quarter_does_not_override_explicit_fiscal_period(self):
        found=self.discover('''<article><h2>Q1 FY2027 Earnings Call</h2><p>September 24, 2026</p>
          <a href="https://video.test/current">Webcast</a></article>''',call_year=2026,quarter='Q3')
        self.assertEqual(found.event_identity['fiscal_year'],2027)
        self.assertEqual(found.event_identity['fiscal_quarter'],'Q1')

    def test_unique_scoped_official_fiscal_event_can_bootstrap_seven_day_shift(self):
        found=self.discover('''<article><h2>Q4 FY2026 Earnings Call</h2><p>October 1, 2026</p>
          <a href="/event/q4-2026">Event details</a><a href="https://video.test/current">Webcast</a></article>''')
        self.assertEqual(found.webcast_date,date(2026,10,1))
        self.assertTrue(found.event_identity['date_shift_verified'])

    def test_unknown_date_shift_without_fiscal_and_provider_proof_is_rejected(self):
        found=self.discover('''<article><h2>Earnings Call</h2><p>October 1, 2026</p></article>''')
        self.assertIsNone(found)

    def test_multiple_nearby_periods_cannot_bootstrap_shift(self):
        found=self.discover('''<div><article><h2>Q3 FY2026 Earnings Call</h2><p>October 1, 2026</p>
          <a href="https://video.test/one">Webcast</a></article>
          <article><h2>Q4 FY2026 Earnings Call</h2><p>October 2, 2026</p>
          <a href="https://video.test/two">Webcast</a></article></div>''')
        self.assertIsNone(found)

    def test_hidden_and_navigation_links_are_not_candidates(self):
        found=self.discover('''<div><article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026</p>
          <div style="display:none"><a href="https://video.test/old">Webcast</a></div>
          <nav><a href="https://video.test/nav">Webcast</a></nav></article></div>''')
        self.assertIsNone(found.webcast_url)

    def test_typed_proof_has_exact_url_and_date_not_just_free_text(self):
        self.assertIsNone(read_route_proof('[target-linked:webcast_url=2026-09-24] Earnings call'))
        self.assertIsNone(read_route_proof('issuer-route-v2:{broken'))
        self.assertIsNone(normalize_route(self.url,'https://pixel.tracking.example/webcast'))

    def test_fiscal_parse_never_reads_calendar_month_as_quarter(self):
        self.assertEqual(fiscal_period('September 24, 2026'),(None,None))
        self.assertEqual(fiscal_period('Third Quarter FY2027 Earnings Call'),(2027,'Q3'))

    def run_pages(self, pages, **values):
        call={**self.call,**values}
        def fetch(url):
            content=pages.get(url,'<html></html>')
            self.enricher._page_documents[url]=content
            self.enricher._page_fetch_succeeded=True
            return self.enricher._extract_page_details(content,url)
        with mock.patch.object(self.enricher,'_fetch_event_page',side_effect=fetch), \
             mock.patch.object(self.enricher,'_fetch_event_page_with_browser',return_value=('',None)), \
             mock.patch('data_pipeline.collectors.schedules.enricher.database') as db:
            result=self.enricher.verify_call(call,dry_run=True)
        for name in ('update_verified_schedule_time','update_official_schedule_discovery','record_schedule_enrichment_outcome','get_schedule_enrichment_circuit'):
            getattr(db,name).assert_not_called()
        return result

    def test_stored_weak_page_does_not_prevent_current_index_selection(self):
        stored='https://ir.example.com/event/old'
        result=self.run_pages({stored:'<p>Q3 FY2026 earnings call June 24, 2026</p>',
            self.url:'''<article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026 at 8 a.m. ET</p>
              <a href="https://video.test/current">Webcast</a></article>'''},event_url=stored)
        self.assertEqual(result.scheduled_at_utc.hour,12)
        self.assertEqual(result.webcast_url,'https://video.test/current')
        self.assertEqual(len(self.enricher.last_dry_run['pages_checked']),2)

    def test_conflicting_index_and_stored_page_do_not_choose_first(self):
        stored='https://ir.example.com/event/current'
        result=self.run_pages({stored:'<p>Q4 FY2026 earnings call September 24, 2026 at 8 a.m. ET</p>',
            self.url:'<p>Q4 FY2026 earnings call September 24, 2026 at 9 a.m. ET</p>'},event_url=stored)
        self.assertIsNone(result)
        self.assertTrue(self.enricher.last_dry_run['conflicted'])

    def test_new_shifted_time_parsed_after_strong_route_identification(self):
        result=self.run_pages({self.url:'''<article><h2>Q4 FY2026 Earnings Call</h2><p>October 1, 2026 at 8 a.m. ET</p>
          <a href="https://video.test/current">Webcast</a></article>'''})
        self.assertEqual(result.webcast_date,date(2026,10,1))
        self.assertTrue(result.event_identity['date_shift_verified'])

    def test_useful_provider_route_survives_missing_exact_clock(self):
        result=self.run_pages({self.url:'''<article><h2>Q4 FY2026 Earnings Call</h2><p>September 24, 2026</p>
          <a href="https://video.test/current">Webcast</a></article>'''})
        self.assertIsNone(result)
        self.assertEqual(self.enricher.last_dry_run['discovery']['webcast_url'],'https://video.test/current')

    def test_verified_time_does_not_keep_only_old_card_playback(self):
        result=self.run_pages({self.url:'''<div><article><h2>Q3 FY2026 Earnings Call</h2><p>June 24, 2026</p>
          <a href="https://video.test/old">Webcast</a></article><article><h2>Q4 FY2026 Earnings Call</h2>
          <p>September 24, 2026 at 8 a.m. ET</p></article></div>'''})
        self.assertIsNotNone(result)
        self.assertIsNone(result.webcast_url)

    def test_release_date_has_no_call_identity(self):
        found=self.discover('<article><h2>Q4 FY2026 Financial Results Release</h2><p>September 24, 2026</p></article>')
        self.assertFalse(found.event_identity['identity_verified'])
        self.assertEqual(read_route_proof(found.evidence)['event_type'],'earnings_date')

    def test_same_stored_call_page_withdrawal_is_explicit_not_network_failure(self):
        result=self.run_pages({self.url:'<article><h2>Q4 FY2026 earnings call</h2><p>September 24, 2026</p></article>'},
            event_url=self.url,scheduled_at_utc=datetime(2026,9,24,12))
        self.assertIsNone(result)
        self.assertTrue(self.enricher.last_dry_run['official_time_withdrawn'])

    def test_cancelled_current_call_cannot_keep_old_exact_start(self):
        result=self.run_pages({self.url:'<article><h2>Q4 FY2026 earnings call</h2><p>September 24, 2026 at 8 a.m. ET has been cancelled.</p></article>'})
        self.assertIsNone(result)
        self.assertIn('cancelled',self.enricher.last_dry_run['unavailable_statuses'])

    def test_machine_time_attribute_scopes_route_date(self):
        found=self.discover('<article><h2>Q4 FY2026 earnings call</h2><time datetime="2026-09-24T12:00:00Z"></time><a href="https://video.test/current">Webcast</a></article>')
        self.assertEqual(found.webcast_date,self.day)
        self.assertEqual(found.webcast_url,'https://video.test/current')

    def test_only_old_archive_cannot_bootstrap_future_calendar_backwards(self):
        found=self.discover('<article><h2>Q3 FY2026 earnings call</h2><p>September 1, 2026</p><a href="https://video.test/old">Webcast</a></article>')
        self.assertIsNone(found)

    def test_captured_issuer_dom_routes_and_times(self):
        cases = (
            ('payx','https://investor.paychex.com/',date(2026,9,23),'2026-09-23T13:30:00+00:00','fknnzy2d',2027,'Q1'),
            ('ctas','https://www.cintas.com/investors/earnings-webcast/event-details',date(2026,9,23),'2026-09-23T14:00:00+00:00','6agfne3p',2027,'Q1'),
            ('acn','https://investor.accenture.com/news-and-events/events-calendar',date(2026,9,24),'2026-10-01T12:00:00+00:00','AccentureFY26Q4Earnings',2026,'Q4'),
        )
        for ticker,url,day,utc,provider,year,quarter in cases:
            with self.subTest(ticker=ticker):
                self.enricher=OfficialScheduleEnricher(api_key='')
                self.url=url
                self.call.update(ticker=ticker.upper(),ir_url=url,webcast_date=day)
                dom=(Path(__file__).parent/'fixtures'/'schedules'/f'{ticker}-20260918.html').read_text()
                result=self.run_pages({url:dom})
                self.assertIsNotNone(result)
                self.assertEqual(result.scheduled_at_utc.isoformat(),utc)
                self.assertIn(provider,result.webcast_url)
                self.assertEqual(result.event_identity['fiscal_year'],year)
                self.assertEqual(result.event_identity['fiscal_quarter'],quarter)
                self.assertEqual(read_route_proof(result.schedule_evidence)['webcast_url'],result.webcast_url)
                self.assertEqual(result.as_database_values()['schedule_discovery_fingerprint'],self.enricher.last_dry_run['discovery']['fingerprint'])

    def test_month_year_without_day_does_not_become_october_twentieth(self):
        self.assertIsNone(self.discover('<article><h2>Q4 FY2026 earnings call</h2><p>October 2026</p><a href="https://video.test/current">Webcast</a></article>'))

if __name__=='__main__': unittest.main()
