"""Browser identity, waiting and persisted time use the same call-start parser."""
from datetime import date, datetime, timezone
import os
import unittest
from unittest import mock

from data_pipeline.collectors.schedules.call_times import parse_call_times
from data_pipeline.collectors.streams.browser.rules import live_event_wait_reason
from data_pipeline.collectors.streams.webcast_learning import (
    WebcastCandidate, candidate_identity_mismatch, live_candidate_identity_confirmation,
    live_event_identity_confirmation, event_datetime_from_text,
)


DAY = date(2026, 9, 23)
QA = ('EXM prepared remarks published September 23, 2026 at 7:00 AM EDT. '
      'EXM live Q&A session September 23, 2026 at 10:30 AM EDT.')


def candidate(text):
    return WebcastCandidate(candidate_id='clock', selectors=(), frame_hostname=None,
                            text=text, aria_label='', title='', href_path=None,
                            tag_name='a', rect={})


class UnifiedBrowserClockRulesTest(unittest.TestCase):
    def test_release_and_qa_use_same_exact_time_for_identity_wait_and_storage(self):
        utc = datetime(2026, 9, 23, 14, 30, tzinfo=timezone.utc)
        self.assertEqual(parse_call_times(QA, DAY).selected.scheduled_at_utc, utc)
        self.assertEqual(live_event_identity_confirmation(QA, target_date=DAY, target_time_utc=utc),
                         'target date and start time matched')
        self.assertIsNone(candidate_identity_mismatch(candidate(QA), target_date=DAY, target_time_utc=utc))
        self.assertIsNotNone(live_candidate_identity_confirmation(candidate(QA), target_date=DAY, target_time_utc=utc))
        reason = live_event_wait_reason(QA, target_date=DAY, target_time_utc=utc,
                                       reference_time_utc=datetime(2026, 9, 23, 12, tzinfo=timezone.utc))
        self.assertIn(utc.isoformat(), reason)

    def test_early_entry_is_measured_from_qa_clock(self):
        utc = datetime(2026, 9, 23, 14, 30, tzinfo=timezone.utc)
        with mock.patch.dict(os.environ, {'DATE_STREAM_EARLY_ENTRY_MINUTES': '5'}):
            self.assertIsNotNone(live_event_wait_reason(QA, target_date=DAY,
                reference_time_utc=utc.replace(minute=24)))
            self.assertIsNone(live_event_wait_reason(QA, target_date=DAY,
                reference_time_utc=utc.replace(minute=25)))

    def test_explicit_est_in_summer_retains_its_fixed_offset(self):
        text = 'EXM earnings call September 23, 2026 at 10:30 AM EST'
        utc = datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc)
        self.assertEqual(parse_call_times(text, DAY).selected.scheduled_at_utc, utc)
        self.assertEqual(live_event_identity_confirmation(text, target_date=DAY, target_time_utc=utc),
                         'target date and start time matched')
        reason = live_event_wait_reason(text, target_date=DAY,
            reference_time_utc=datetime(2026, 9, 23, 15, 10, tzinfo=timezone.utc))
        self.assertIn(utc.isoformat(), reason)

    def test_matched_clockless_event_obeys_verified_db_start(self):
        text = 'EXM earnings call September 23, 2026'
        utc = datetime(2026, 9, 23, 14, 30, tzinfo=timezone.utc)
        reason = live_event_wait_reason(text, target_date=DAY, target_time_utc=utc,
            reference_time_utc=datetime(2026, 9, 23, 14, tzinfo=timezone.utc))
        self.assertIn(utc.isoformat(), reason)
        self.assertIsNone(live_event_wait_reason(text, target_date=DAY, target_time_utc=utc,
            reference_time_utc=utc))

    def test_conflicting_same_call_clocks_cannot_confirm_or_start_capture(self):
        text = ('EXM earnings call September 23, 2026 at 10:30 AM EDT. '
                'EXM earnings call September 23, 2026 at 11:30 AM EDT.')
        self.assertIsNone(live_event_identity_confirmation(text, target_date=DAY))
        self.assertIn('ambiguous', live_event_wait_reason(text, target_date=DAY,
            reference_time_utc=datetime(2026, 9, 23, 16, tzinfo=timezone.utc)))
        self.assertIsNone(live_candidate_identity_confirmation(candidate(text), target_date=DAY))

    def test_tbd_and_postponed_are_wait_states(self):
        for text in ('EXM earnings call September 23, 2026; time to be announced',
                     'EXM earnings call September 23, 2026 at 10:30 AM EDT postponed'):
            with self.subTest(text=text):
                self.assertIsNone(live_event_identity_confirmation(text, target_date=DAY))
                self.assertIsNotNone(live_event_wait_reason(text, target_date=DAY))

    def test_unrelated_event_never_supplies_a_wait_clock_or_identity(self):
        text = 'EXM industry conference September 23, 2026 at 10:30 AM EDT'
        self.assertIsNone(parse_call_times(text, DAY).selected)
        self.assertIsNone(live_event_identity_confirmation(text, target_date=DAY))
        self.assertIsNone(live_event_wait_reason(text, target_date=DAY,
            reference_time_utc=datetime(2026, 9, 23, 12, tzinfo=timezone.utc)))

    def test_release_only_is_not_an_exact_live_start(self):
        text = 'EXM financial results release September 23, 2026 at 7:00 AM EDT'
        self.assertIsNone(parse_call_times(text, DAY).selected)
        self.assertIsNone(live_event_wait_reason(text, target_date=DAY,
            reference_time_utc=datetime(2026, 9, 23, 10, tzinfo=timezone.utc)))

    def test_actual_same_day_call_time_mismatch_still_rejected(self):
        text = 'EXM earnings call September 23, 2026 at 7:00 AM EDT'
        wanted = datetime(2026, 9, 23, 17, tzinfo=timezone.utc)
        self.assertIsNone(live_event_identity_confirmation(text, target_date=DAY, target_time_utc=wanted))
        self.assertIn('start time contradicts', candidate_identity_mismatch(candidate(text),
            target_date=DAY, target_time_utc=wanted))

    def test_legacy_replay_datetime_parser_retains_existing_semantics(self):
        self.assertEqual(event_datetime_from_text(QA, default_date=DAY).hour, 7)


if __name__ == '__main__':
    unittest.main()
