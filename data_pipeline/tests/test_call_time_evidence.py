"""Issuer call clocks must remain in their event, with explicit zone evidence."""
from datetime import date
import unittest

from lxml import html
from data_pipeline.collectors.schedules.call_times import parse_call_times, schedule_time_text


class ScopedCallTimeEvidenceTest(unittest.TestCase):
    day = date(2026, 9, 23)

    def parse(self, value, **kwargs):
        return parse_call_times(value, self.day, **kwargs)

    def utc(self, value, expected='2026-09-23T12:00:00+00:00'):
        result = self.parse(value)
        self.assertIsNotNone(result.selected, (result.status, value))
        self.assertEqual(result.selected.scheduled_at_utc.isoformat(), expected)

    def test_hour_only_and_punctuated_or_parenthesized_zone(self):
        for clock in ('8 a.m. ET', '8 AM ET', '8:00 a.m. Eastern Time', '8:00 AM (ET)'):
            with self.subTest(clock=clock):
                self.utc(f'Q1 2027 Earnings Call September 23, 2026 at {clock}')

    def test_day_month_year_supports_issuer_calendar_formats(self):
        for day in ('23 Sep, 2026', '23 September 2026', '23 Sep. 2026'):
            self.utc('Earnings call ' + day + ', 08:00 AM ET')
        result = parse_call_times('Earnings call 01 Oct, 2026, 08:00 AM ET', date(2026, 10, 1))
        self.assertEqual(result.selected.scheduled_at_utc.isoformat(), '2026-10-01T12:00:00+00:00')

    def test_month_followed_only_by_year_is_not_a_day(self):
        self.assertIsNone(parse_call_times('Earnings call October 2026 at 8 AM ET', date(2026, 10, 20)).selected)

    def test_multiline_heading_date_and_clock_in_one_card(self):
        self.utc('Q1 2027 Earnings Call\nSeptember 23, 2026\n8 a.m. ET')
        self.utc('<article><h2>Q1 2027 Earnings Call</h2><p>September 23, 2026</p><p>8 a.m. ET</p></article>')

    def test_comment_and_script_tails_are_visible_without_treating_comment_as_element(self):
        self.utc('<article><h2>Q1 FY2027 Earnings Call</h2><!-- CMS marker -->'
                 'September 23, 2026 <script>invisible("9 AM ET")</script>8 AM ET</article>')
        self.utc('<article><!-- CMS event title -->Earnings Call September 23, 2026 at 8 AM ET</article>')
        self.assertIsNone(self.parse('<article><!-- Earnings Call September 23, 2026 at 9 AM ET -->'
                                    '<h2>Earnings Call</h2><p>Time to be announced</p></article>').selected)

    def test_call_paragraph_retains_its_card_fiscal_identity(self):
        result = self.parse('<article><h2>Acme Q1 FY2027 Earnings Call</h2>'
                            '<p>Conference call September 23, 2026 at 8 a.m. ET</p></article>')
        self.assertIn('Q1 FY2027', result.selected.evidence)

    def test_separate_event_cards_do_not_lend_each_other_times(self):
        self.assertIsNone(self.parse('''<main>
        <article><h2>Q1 2027 Earnings Call</h2><p>September 23, 2026</p><p>Time to be announced</p></article>
        <article><h2>Industry Conference</h2><p>September 23, 2026</p><p>8 a.m. ET</p></article>
        </main>''').selected)
        self.assertIsNone(self.parse('''<div>
        <div><h2>Q1 2027 Earnings Call</h2><p>September 23, 2026</p></div>
        <div><h2>Industry Conference</h2><p>September 23, 2026 8 a.m. ET</p></div>
        </div>''').selected)

    def test_paychex_explicit_release_conference_call_title_is_still_a_call(self):
        self.utc('<article><p>September 23, 2026 8 AM EDT</p>'
                 '<h3>First Quarter Fiscal 2027 Earnings Release Conference Call</h3></article>')
        self.utc('{"@type":"Event", "name":"First Quarter Fiscal 2027 Earnings Release Conference Call",'
                 '"startDate":"2026-09-23T08:00:00-04:00"}')
        self.assertIsNone(self.parse('{"@type":"Event", "name":"First Quarter Fiscal 2027 Earnings Release",'
                                    '"startDate":"2026-09-23T08:00:00-04:00"}').selected)

    def test_release_and_prepared_remarks_are_not_call_starts(self):
        for title in ('Earnings Results', 'Earnings release', 'Prepared remarks webcast', 'Earnings webcast replay'):
            with self.subTest(title=title):
                self.assertIsNone(self.parse('{"@type":"Event","name":"' + title + '","startDate":"2026-09-23T08:00:00-04:00"}').selected)
        value = 'Prepared remarks webcast September 23, 2026 at 7 a.m. ET. Earnings conference call September 23, 2026 at 8 a.m. ET.'
        self.utc(value)

    def test_replay_end_and_publication_cannot_become_start(self):
        self.utc('Earnings webcast September 23, 2026 at 8 a.m. ET, replay available until September 24, 2026 at 9 a.m. ET.')
        self.assertIsNone(self.parse('{"@type":"NewsArticle","headline":"Earnings call", "datePublished":"2026-09-23T08:00:00-04:00"}').selected)

    def test_q_and_a_is_live_call_when_prepared_audio_has_earlier_clock(self):
        self.utc('Prepared remarks posted September 23, 2026 at 7 a.m. ET. Live Q&A session September 23, 2026 at 8 a.m. ET.')

    def test_visible_and_semantic_start_conflict_is_explicit(self):
        result = self.parse('''<article><h2>Earnings Call</h2>
        <time datetime="2026-09-23T09:00:00-04:00">September 23, 2026 at 8 a.m. ET</time></article>''')
        self.assertEqual(result.status, 'ambiguous')
        self.assertIsNone(result.selected)

    def test_jsonld_release_start_does_not_conflict_with_real_call(self):
        self.utc('''<article><h2>Earnings Call</h2><p>September 23, 2026 at 8 a.m. ET</p></article>
        <script type="application/ld+json">{"@type":"Event","name":"Earnings Results", "startDate":"2026-09-23T07:00:00-04:00"}</script>''')

    def test_jsonld_hidden_and_semantic_dom(self):
        self.utc('''<article><h2>Earnings Call</h2><time datetime="2026-09-23T08:00:00-04:00"></time>
        <div hidden>Earnings call September 23, 2026 at 9 a.m. ET</div></article>''')

    def test_explicit_standard_abbreviation_is_fixed_offset(self):
        self.utc('Earnings Call September 23, 2026 at 8 a.m. EST', '2026-09-23T13:00:00+00:00')

    def test_regional_zone_observes_dst_and_rejects_ambiguous_wall_clock(self):
        self.utc('Earnings Call September 23, 2026 at 8 a.m. ET')
        for day, text in [(date(2026, 3, 8), 'Earnings Call March 8, 2026 at 2:30 AM ET'),
                          (date(2026, 11, 1), 'Earnings Call November 1, 2026 at 1:30 AM ET')]:
            self.assertIsNone(parse_call_times(text, day).selected)
        fixed = parse_call_times('Earnings call November 1, 2026 at 1:30 AM EDT', date(2026, 11, 1))
        self.assertEqual(fixed.selected.scheduled_at_utc.hour, 5)

    def test_no_date_or_no_zone_stays_unknown(self):
        for value in ('Earnings call at 8 AM ET', 'Earnings call September 23, 2026 at 8 AM',
                      'Earnings call September 23, 2026 before market open'):
            self.assertEqual(self.parse(value).status, 'unknown')

    def test_arbitrary_date_shift_requires_explicit_identity_authorization(self):
        value = 'Q1 2027 Earnings Call October 1, 2026 at 8 a.m. ET'
        self.assertIsNone(self.parse(value).selected)
        self.assertEqual(self.parse(value, allow_date_shift=True).selected.webcast_date, date(2026, 10, 1))

    def test_ics_dtstart_only_with_call_label_and_explicit_zone(self):
        event = ('BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Q1 2027 Earnings Call\n'
                 'DTSTART;TZID=America/New_York:20260923T080000\nDTEND:20260923T140000Z\n'
                 'END:VEVENT\nEND:VCALENDAR')
        self.utc(event)
        self.utc(event.replace('DTSTART;TZID=America/New_York:20260923T080000', 'DTSTART:20260923T120000Z'))
        for changed in (event.replace('Earnings Call', 'Earnings Results'),
                        event.replace('TZID=America/New_York:', ':'),
                        event.replace('DTEND:', 'RRULE:FREQ=DAILY\nDTEND:'),
                        event.replace('DTEND:', 'STATUS:CANCELLED\nDTEND:'),
                        event.replace('DTSTART;TZID=America/New_York:20260923T080000', 'DTSTART;VALUE=DATE:20260923')):
            self.assertIsNone(self.parse(changed).selected)

    def test_sibling_card_replay_semantics_cannot_override_live_call(self):
        self.utc('''<section><article><h2>Q1 Earnings Call</h2><p>September 23, 2026 at 8 AM ET</p></article>
        <article><h2>Earnings Webcast Replay</h2><p>September 23, 2026 at 10 AM ET</p></article></section>''')

    def test_explicit_cancellation_or_postponement_is_not_a_verified_old_clock(self):
        for suffix, expected in [('has been cancelled', 'cancelled'), ('has been postponed', 'postponed'),
                                 ('time to be announced', 'time_tbd')]:
            result = self.parse('Earnings call September 23, 2026 at 8 AM ET ' + suffix)
            self.assertEqual(result.status, expected)
            self.assertIsNone(result.selected)
        result = self.parse('{"@type":"Event","name":"Earnings call","startDate":"2026-09-23T08:00:00-04:00","eventStatus":"https://schema.org/EventCancelled"}')
        self.assertEqual(result.status, 'cancelled')

    def test_prior_cancelled_event_does_not_invalidate_current_call(self):
        self.utc('<article><h2>Earnings call</h2><p>June 23, 2026 cancelled</p></article>'
                 '<article><h2>Earnings call</h2><p>September 23, 2026 at 8 AM ET</p></article>')

    def test_serialized_blocks_keep_unicode_and_can_round_trip(self):
        value = schedule_time_text(html.fromstring('<article><h2>Société earnings call</h2><p>September 23, 2026 8 a.m. ET</p></article>'))
        self.assertIn('Société', value)
        self.utc(value)


if __name__ == '__main__':
    unittest.main()
