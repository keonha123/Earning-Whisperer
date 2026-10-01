"""A fallback standard-zone label must not defer a proven live provider clock."""
from datetime import date, datetime, timezone
from unittest import mock
import unittest

from data_pipeline.collectors.schedules.call_times import parse_call_times, seasonal_abbreviation_conflict
from data_pipeline.collectors.schedules.browser_observation import observe_browser_time, validated_browser_values
from data_pipeline.collectors.streams.browser.rules import live_event_wait_reason
from data_pipeline.tests.test_browser_schedule_observation import fixture

DAY = date(2026, 9, 23)
CARD = 'EXM earnings webcast September 23, 2026 8:00 AM CST'
PROVIDER = 'EXM earnings webcast September 23, 2026 1:00 PM GMT'
VERIFIED = datetime(2026, 9, 23, 13, tzinfo=timezone.utc)


class SeasonalClockConflictTest(unittest.TestCase):
    def test_literal_cst_without_independent_clock_stays_fixed(self):
        parsed = parse_call_times(CARD, DAY).selected
        self.assertEqual(parsed.scheduled_at_utc.hour, 14)
        self.assertFalse(seasonal_abbreviation_conflict(parsed, None))
        self.assertIn('14:00:00', live_event_wait_reason(CARD, target_date=DAY,
            reference_time_utc=VERIFIED))

    def test_proven_provider_clock_does_not_wait_an_extra_hour_on_ir_fallback(self):
        self.assertTrue(seasonal_abbreviation_conflict(parse_call_times(CARD, DAY).selected, VERIFIED))
        self.assertIsNone(live_event_wait_reason(CARD, target_date=DAY,
            target_time_utc=VERIFIED, reference_time_utc=VERIFIED))
        self.assertIn('13:00:00', live_event_wait_reason(CARD, target_date=DAY,
            target_time_utc=VERIFIED, reference_time_utc=VERIFIED.replace(hour=12)))

    def test_browser_does_not_replace_proven_db_clock_with_ambiguous_label(self):
        agent, _ = fixture()
        agent.target_time_utc = VERIFIED
        with mock.patch('data_pipeline.live_telemetry.emit_live_event') as emit:
            observation = observe_browser_time(agent, CARD)
        self.assertEqual(observation['source_timezone'], 'CST')
        self.assertIn(('schedule', 'browser_start_timezone_conflict'), [x.args[:2] for x in emit.call_args_list])

    def test_provider_observation_survives_later_issuer_standard_label(self):
        agent, call = fixture()
        provider = observe_browser_time(agent, PROVIDER, evidence_url=agent.live_target_proof['target_url'])
        self.assertEqual(provider['scheduled_at_utc'], VERIFIED.isoformat())
        self.assertIs(observe_browser_time(agent, CARD), provider)
        self.assertIs(agent.schedule_observation, provider)
        self.assertEqual(validated_browser_values(call, provider)['scheduled_at_utc'], VERIFIED.replace(tzinfo=None))

    def test_provider_corrects_prior_standard_label_observation(self):
        agent, _ = fixture()
        self.assertEqual(observe_browser_time(agent, CARD)['source_timezone'], 'CST')
        provider = observe_browser_time(agent, PROVIDER, evidence_url=agent.live_target_proof['target_url'])
        self.assertEqual(provider['scheduled_at_utc'], VERIFIED.isoformat())
        self.assertIs(observe_browser_time(agent, CARD), provider)

    def test_same_route_identity_refresh_preserves_provider_clock(self):
        from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
        agent, _ = fixture()
        agent.target_year = agent.target_quarter = None
        agent._signal_live_target_identity_ready = lambda: None
        proof = agent.live_target_proof
        provider = observe_browser_time(agent, PROVIDER, evidence_url=proof['target_url'])
        BrowserWebcastAgent._mark_live_target_identity_confirmed(agent, CARD,
            source_url=proof['source_url'], target_url=proof['target_url'])
        self.assertIs(agent.schedule_observation, provider)
        BrowserWebcastAgent._mark_live_target_identity_confirmed(agent, CARD,
            source_url=proof['source_url'], target_url='https://app.webinar.net/Other123')
        self.assertIsNot(agent.schedule_observation, provider)
        self.assertEqual(agent.schedule_observation['source_timezone'], 'CST')

    def test_db_writer_receives_conflicting_label_for_durable_consensus(self):
        agent, call = fixture()
        observed = observe_browser_time(agent, CARD)
        for value in [VERIFIED, VERIFIED.replace(tzinfo=None), '2026-09-23 13:00:00', '2026-09-23T09:00:00-04:00']:
            with self.subTest(value=value):
                call['scheduled_at_utc'] = value
                values = validated_browser_values(call, observed)
                self.assertEqual(values['clock_observations'][0]['value'], '2026-09-23T14:00:00+00:00')

    def test_different_wall_clock_is_not_treated_as_seasonal_label_error(self):
        for target in [VERIFIED.replace(hour=12), VERIFIED.replace(day=24), VERIFIED.replace(minute=30)]:
            self.assertFalse(seasonal_abbreviation_conflict(parse_call_times(CARD, DAY).selected, target))
        agent, _ = fixture()
        agent.target_time_utc = VERIFIED.replace(hour=12)
        self.assertIsNotNone(observe_browser_time(agent, CARD))

    def test_winter_standard_time_and_explicit_daylight_times_are_unmodified(self):
        winter = date(2026, 12, 23)
        parsed = parse_call_times(CARD.replace('September', 'December'), winter).selected
        self.assertFalse(seasonal_abbreviation_conflict(parsed, datetime(2026, 12, 23, 13, tzinfo=timezone.utc)))
        daylight = parse_call_times(CARD.replace('CST', 'CDT'), DAY).selected
        self.assertFalse(seasonal_abbreviation_conflict(daylight, VERIFIED.replace(hour=12)))


if __name__ == '__main__':
    unittest.main()
