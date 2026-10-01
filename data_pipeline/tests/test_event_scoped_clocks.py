"""Mixed calendars must not lend another event's clock/status to a target call."""
from datetime import date
import json
import unittest

from lxml import html

from data_pipeline.collectors.schedules.call_times import parse_call_times, schedule_time_text


TARGET = dict(expected_fiscal_year=2026, expected_fiscal_quarter='Q4')
DAY = date(2026, 10, 1)
MIXED_CALENDAR = '''<main><h1>Events Calendar</h1>
<article><h2>Example Q4 FY2026 Earnings Conference Call</h2>
<p>01 Oct, 2026</p><p>08:00 AM ET</p><a href="/q4">Webcast</a></article>
<article><h2>Example Investor Day</h2><p>14 Oct, 2026</p>
<p>08:30 AM ET</p><a href="/investor-day">Webcast</a></article></main>'''


class TargetEventClockTest(unittest.TestCase):
    def parse(self, value, **kwargs):
        return parse_call_times(value, DAY, allow_date_shift=True, **TARGET, **kwargs)

    def assert_start(self, value, expected='2026-10-01T12:00:00+00:00'):
        result = self.parse(value)
        self.assertEqual(result.status, 'verified', result)
        self.assertEqual(result.selected.scheduled_at_utc.isoformat(), expected)

    def test_mixed_calendar_earnings_and_investor_day(self):
        self.assert_start(MIXED_CALENDAR)
        self.assert_start(schedule_time_text(html.fromstring(MIXED_CALENDAR)))

    def test_non_earnings_event_excluded_without_fiscal_target(self):
        result = parse_call_times(MIXED_CALENDAR, date(2026, 9, 24), allow_date_shift=True)
        self.assertEqual(result.selected.scheduled_at_utc.isoformat(), '2026-10-01T12:00:00+00:00')

    def test_generic_webcast_paragraph_keeps_non_earnings_heading(self):
        self.assert_start('''<main><article><h2>Q4 FY2026 Earnings Call</h2>
            <p>Conference call October 1, 2026 at 8 AM ET</p></article>
            <article><h2>Investor Day</h2>
            <p>Webcast October 14, 2026 at 8:30 AM ET</p></article></main>''')

    def test_adjacent_fiscal_earnings_does_not_share_date_shift_authorization(self):
        value = '''<main><article><h2>Q4 FY2026 Earnings Call</h2>
            <p>October 1, 2026 at 8 AM ET</p></article>
            <article><h2>Q3 FY2026 Earnings Call</h2>
            <p>July 1, 2026 at 8:30 AM ET</p></article></main>'''
        self.assert_start(value)

    def test_nearby_unrelated_fiscal_period_is_filtered_without_date_shift(self):
        value = 'Q3 FY2026 Earnings Call October 1, 2026 at 8 AM ET'
        result = parse_call_times(value, DAY, **TARGET)
        self.assertEqual(result.status, 'unknown')

    def test_prior_year_same_quarter_is_filtered(self):
        value = ('Q4 FY2025 Earnings Call October 1, 2025 at 8 AM ET\n\n'
                 'Q4 FY2026 Earnings Call October 1, 2026 at 8 AM ET')
        self.assert_start(value)

    def test_same_target_real_clock_conflict_remains_ambiguous(self):
        value = MIXED_CALENDAR + '''<article><h2>Q4 FY2026 Earnings Call</h2>
             <p>October 1, 2026 at 9 AM ET</p></article>'''
        result = self.parse(value)
        self.assertTrue(result.conflicted)
        self.assertIsNone(result.selected)
        self.assertEqual(len(result.candidates), 2)

    def test_same_event_visible_semantic_conflict_remains_ambiguous(self):
        result = self.parse('''<article><h2>Q4 FY2026 Earnings Call</h2>
        <time datetime="2026-10-01T09:00:00-04:00">October 1, 2026 at 8 AM ET</time></article>''')
        self.assertTrue(result.conflicted)
        self.assertEqual(len(result.candidates), 2)

    def test_other_period_cancelled_or_tbd_does_not_hide_target(self):
        for suffix in ('has been cancelled', 'has been postponed', 'time to be announced'):
            with self.subTest(suffix=suffix):
                self.assert_start(MIXED_CALENDAR + '<article><h2>Q3 FY2026 Earnings Call</h2>'
                                  '<p>July 1, 2026 ' + suffix + '</p></article>')

    def test_unrelated_tbd_event_does_not_hide_target(self):
        self.assert_start(MIXED_CALENDAR + '<article><h2>Investor Day</h2>'
                          '<p>Webcast October 14, 2026 time to be announced</p></article>')

    def test_jsonld_same_event_conflicting_clock_is_not_discarded(self):
        value = MIXED_CALENDAR + '<script type="application/ld+json">' + json.dumps({
            '@type': 'Event', 'name': 'Q4 FY2026 Earnings Call',
            'startDate': '2026-10-01T09:00:00-04:00'}) + '</script>'
        self.assertEqual(self.parse(value).status, 'ambiguous')

    def test_same_target_cancellation_is_preserved(self):
        result = self.parse(MIXED_CALENDAR + '<article><h2>Q4 FY2026 Earnings Call</h2>'
                            '<p>October 1, 2026 has been postponed</p></article>')
        self.assertEqual(result.status, 'postponed')
        self.assertIsNone(result.selected)

    def test_generic_authenticated_provider_title_is_still_allowed(self):
        self.assert_start('Conference Call October 1, 2026 at 8 AM ET')

    def test_unrelated_named_events_do_not_become_calls_from_webcast_label(self):
        for title in ('Investor Day', 'Capital Markets Day', 'Annual Shareholder Meeting',
                      'Technology Conference', 'Post Earnings Analyst Call'):
            with self.subTest(title=title):
                value = '<article><h2>' + title + '</h2><p>Webcast October 1, 2026 at 8 AM ET</p></article>'
                self.assertEqual(self.parse(value).status, 'unknown')

    def test_jsonld_scope_keeps_description_with_its_event_title(self):
        events = [dict(**{'@type': 'Event'}, name='Q4 FY2026 Earnings Call',
                       startDate='2026-10-01T08:00:00-04:00'),
                  dict(**{'@type': 'Event'}, name='Investor Day Webcast',
                       startDate='2026-10-14T08:30:00-04:00',
                       description='Webcast October 14, 2026 at 8:30 AM ET')]
        self.assert_start(json.dumps(events))

    def test_jsonld_other_period_cancelled_does_not_contaminate(self):
        events = [dict(**{'@type': 'Event'}, name='Q4 FY2026 Earnings Call',
                       startDate='2026-10-01T08:00:00-04:00'),
                  dict(**{'@type': 'Event'}, name='Q3 FY2026 Earnings Call',
                       startDate='2026-07-01T08:30:00-04:00',
                       eventStatus='https://schema.org/EventCancelled')]
        self.assert_start(json.dumps(events))

    def test_ical_filters_distinct_fiscal_event_and_investor_day(self):
        def event(title, stamp):
            return f'BEGIN:VEVENT\nSUMMARY:{title}\nDTSTART:{stamp}\nEND:VEVENT\n'
        value = ('BEGIN:VCALENDAR\n' + event('Q4 FY2026 Earnings Call', '20261001T120000Z')
                 + event('Q3 FY2026 Earnings Call', '20260701T120000Z')
                 + event('Investor Day Webcast', '20261014T123000Z') + 'END:VCALENDAR')
        self.assert_start(value)

    def test_release_and_call_clock_stay_distinct(self):
        self.assert_start('Q4 FY2026 earnings release October 1, 2026 at 7 AM ET. '
                          'Q4 FY2026 earnings conference call October 1, 2026 at 8 AM ET.')


if __name__ == '__main__':
    unittest.main()
