"""Review regressions: clock and route proof must describe the same event."""
from datetime import date
import json
import unittest
from unittest.mock import patch

from data_pipeline.collectors.schedules.call_times import BLOCK_PREFIX, parse_call_times
from data_pipeline.collectors.schedules.enricher import OfficialScheduleEnricher
from data_pipeline.collectors.schedules.event_routes import read_route_proof


class EventRouteReviewTest(unittest.TestCase):
    def setUp(self):
        self.index = 'https://issuer.test/investors/events/'
        self.detail = self.index + 'event-details/2026/q4/'
        self.provider = 'https://provider.test/target'
        self.day = date(2026, 10, 1)
        self.call = dict(id=1, ticker='TEST', company_name='Example Company',
                         ir_url=self.index, webcast_date=self.day, schedule_revision=1)
        self.enricher = OfficialScheduleEnricher(api_key='')

    def run_pages(self, pages, **overrides):
        def fetch(url):
            content = pages.get(url, '<html><p>Not found</p></html>')
            self.enricher._page_documents[url] = content
            self.enricher._page_fetch_succeeded = True
            return self.enricher._extract_page_details(content, url)
        with patch.object(self.enricher, '_fetch_event_page', side_effect=fetch), \
             patch.object(self.enricher, '_fetch_event_page_with_browser', return_value=('', None)), \
             patch.object(self.enricher, '_search_event_results', side_effect=AssertionError('search disabled')), \
             patch('data_pipeline.collectors.schedules.enricher.database') as db:
            result = self.enricher.verify_call({**self.call, **overrides}, dry_run=True)
        db.update_verified_schedule_time.assert_not_called()
        return result

    def test_clock_date_and_route_proof_date_cannot_be_merged_when_different(self):
        pages = {self.index: '''<main><article><h2>Conference Call</h2>
          <p>October 1, 2026 at 8 AM ET</p></article>
          <article><h2>Q4 FY2026 Earnings Call</h2><p>October 2, 2026</p>
          <a href="https://provider.test/target">Webcast</a></article></main>'''}
        result = self.run_pages(pages)
        if result is not None:
            proof = read_route_proof(result.schedule_evidence)
            self.assertTrue(proof is None or proof['date'] == result.webcast_date.isoformat(), result)

    def test_discovered_parent_identity_cannot_change_to_wrong_quarter_on_detail(self):
        pages = {self.index: f'''<article><h2><a href="{self.detail}">Q4 FY2026 Earnings</a></h2>
          <p>October 1, 2026</p></article>''',
          self.detail: '''<article><h2>Q3 FY2026 Earnings Call</h2>
          <p>October 1, 2026 at 8 AM ET</p>
          <a href="https://provider.test/wrong-quarter">Webcast</a></article>'''}
        result = self.run_pages(pages)
        self.assertTrue(result is None or result.webcast_url != 'https://provider.test/wrong-quarter', result)
        discovery = self.enricher.last_dry_run['discovery']
        self.assertTrue(discovery is None or discovery['webcast_url'] != 'https://provider.test/wrong-quarter', discovery)

    def test_date_shift_authorization_cannot_escape_to_unidentified_sibling(self):
        value = '\n'.join(BLOCK_PREFIX + json.dumps({'text': text}) for text in (
            'Q4 FY2026 Earnings Call October 1, 2026',
            'Conference Call October 14, 2026 at 8 AM ET'))
        result = parse_call_times(value, self.day, allow_date_shift=True,
                                 expected_fiscal_year=2026, expected_fiscal_quarter='Q4')
        self.assertIsNone(result.selected, result)

    def test_broad_serialized_scope_does_not_authorize_unidentified_sibling(self):
        value = BLOCK_PREFIX + json.dumps({'text': 'Q4 FY2026 Earnings Call October 1, 2026. '
                                          'Conference Call October 14, 2026 at 8 AM ET'})
        result = parse_call_times(value, self.day, allow_date_shift=True,
                                 expected_fiscal_year=2026, expected_fiscal_quarter='Q4')
        self.assertIsNone(result.selected, result)

    def test_broad_serialized_scope_does_not_choose_wrong_period_inside_grace(self):
        value = BLOCK_PREFIX + json.dumps({'text': 'Q4 FY2026 Earnings Call October 1, 2026. '
                                          'Q3 FY2026 Earnings Call October 1, 2026 at 8 AM ET'})
        result = parse_call_times(value, self.day, allow_date_shift=True,
                                 expected_fiscal_year=2026, expected_fiscal_quarter='Q4')
        self.assertIsNone(result.selected, result)

    def test_broad_serialized_old_period_first_keeps_target_clause(self):
        value = BLOCK_PREFIX + json.dumps({'text': 'Q3 FY2026 Earnings Call July 1, 2026 at 8 AM ET. '
                                          'Q4 FY2026 Earnings Call October 1, 2026 at 8 AM ET'})
        result = parse_call_times(value, date(2026, 9, 24), allow_date_shift=True,
                                 expected_fiscal_year=2026, expected_fiscal_quarter='Q4')
        self.assertIsNotNone(result.selected, result)
        self.assertEqual(result.selected.webcast_date, self.day)

    def test_broad_serialized_unrelated_cancellation_is_excluded(self):
        value = BLOCK_PREFIX + json.dumps({'text': 'Q4 FY2026 Earnings Call October 1, 2026 at 8 AM ET. '
                                          'Q3 FY2026 Earnings Call October 1, 2026 cancelled'})
        result = parse_call_times(value, self.day, allow_date_shift=True,
                                 expected_fiscal_year=2026, expected_fiscal_quarter='Q4')
        self.assertIsNotNone(result.selected, result)

    def test_generic_semantic_time_keeps_own_target_heading_when_shifted(self):
        value = '<article><h2>Q4 FY2026 Earnings Call</h2><p>Conference Call '
        value += '<time datetime="2026-10-01T08:00:00-04:00"></time></p></article>'
        result = parse_call_times(value, date(2026, 9, 24), allow_date_shift=True,
                                 expected_fiscal_year=2026, expected_fiscal_quarter='Q4')
        self.assertIsNotNone(result.selected, result)
        self.assertEqual(result.selected.webcast_date, self.day)

    def test_old_period_first_does_not_hide_identified_shifted_target_clock(self):
        pages = {self.index: '''<main><article><h2>Q3 FY2026 Earnings Call</h2>
          <p>July 1, 2026 at 8 AM ET</p></article>
          <article><h2>Q4 FY2026 Earnings Call</h2>
          <p>October 1, 2026 at 8 AM ET</p></article></main>'''}
        result = self.run_pages(pages, webcast_date=date(2026, 9, 24),
                                verified_fiscal_year=2026, verified_fiscal_quarter='Q4')
        self.assertIsNotNone(result)
        self.assertEqual(result.webcast_date, self.day)


if __name__ == '__main__':
    unittest.main()
