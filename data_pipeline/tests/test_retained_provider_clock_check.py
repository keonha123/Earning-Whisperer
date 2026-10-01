"""An issuer outage may not hide a contradiction on its proven provider page."""
from datetime import timedelta
import json
import unittest
from unittest import mock
from data_pipeline.tests import test_schedule_evidence_retention as fixture
from data_pipeline.storage import schedules


class RetainedProviderClockCheckTest(unittest.TestCase):
    row = fixture.ScheduleEvidenceRetentionTest.row
    update = fixture.ScheduleEvidenceRetentionTest.update
    run_pages = fixture.ScheduleEvidenceRetentionTest.run_pages

    def setUp(self):
        fixture.ScheduleEvidenceRetentionTest.setUp(self)
        self.assertIsNotNone(self.run_pages())
        self.good = self.row()
        self.now += timedelta(hours=7)
        self.enricher._nearby_browser_allowed = lambda: True
        patcher = mock.patch.object(self.enricher, '_fetch_event_page_with_browser', return_value=('', None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def provider(self, clock='3:00 PM GMT', title='Carnival Corporation Q3 2026 Earnings Call', day='September 29, 2026'):
        return f'<article><h2>{title}</h2><p>{day} at {clock}</p></article>'

    def unavailable_issuer(self, provider):
        return {fixture.DETAIL: None, fixture.INDEX: None, fixture.PROVIDER: provider}

    def test_proven_provider_contradiction_demotes_old_clock_without_renewing_expired_route(self):
        self.assertIsNone(self.run_pages(self.unavailable_issuer(self.provider())))
        row = self.row()
        self.assertIsNone(row['scheduled_at_utc'])
        self.assertEqual(row['schedule_revalidation_reason'], 'ambiguous_call_time')
        for field in ('event_url', 'webcast_url', 'schedule_discovery_checked_at',
                      'schedule_discovery_fingerprint', 'schedule_evidence'):
            self.assertEqual(row[field], self.good[field], field)
        proof = json.loads(row['schedule_revalidation_evidence'])
        self.assertEqual(proof['route_action'], 'retained')
        self.assertEqual({x['source'] for x in proof['clock_observations']}, {fixture.DETAIL, fixture.PROVIDER})
        self.assertEqual({x['value'] for x in proof['clock_observations']},
                         {'2026-09-29T14:00:00+00:00', '2026-09-29T15:00:00+00:00'})
        # Repeated provider success cannot resolve the missing issuer side.
        self.now += timedelta(minutes=1)
        self.assertIsNone(self.run_pages(self.unavailable_issuer(self.provider())))
        self.assertIsNone(self.row()['scheduled_at_utc'])

    def test_provider_agreement_does_not_promote_or_refresh_any_verified_timestamp(self):
        self.assertIsNone(self.run_pages(self.unavailable_issuer(self.provider('2:00 PM GMT'))))
        row = self.row()
        for field in ('scheduled_at_utc', 'time_verified_at', 'schedule_discovery_checked_at', 'schedule_revision'):
            self.assertEqual(row[field], self.good[field], field)
        self.update(scheduled_at_utc=None, time_verified_at=None, time_verification_status='unverified')
        self.now += timedelta(minutes=1)
        self.assertIsNone(self.run_pages(self.unavailable_issuer(self.provider())))
        self.assertIsNone(self.row()['scheduled_at_utc'])

    def test_unproven_or_other_event_provider_cannot_demote_clock(self):
        for provider in (self.provider(title='Other Corporation Q3 2026 Earnings Call'),
                         self.provider(title='Carnival Corporation Q2 2026 Earnings Call'),
                         self.provider(title='Carnival Corporation Earnings Call'),
                         self.provider(day='September 30, 2026')):
            with self.subTest(provider=provider):
                self.update(**self.good)
                self.now += timedelta(minutes=1)
                self.assertIsNone(self.run_pages(self.unavailable_issuer(provider)))
                self.assertEqual(self.row()['scheduled_at_utc'], self.good['scheduled_at_utc'])
        self.update(**self.good)
        self.update(schedule_discovery_fingerprint=None)
        self.now += timedelta(minutes=1)
        self.assertIsNone(self.run_pages(self.unavailable_issuer(self.provider())))
        self.assertEqual(self.row()['scheduled_at_utc'], self.good['scheduled_at_utc'])

    def _repository_context(self, mode):
        if mode == 'targeted':
            return schedules.get_call_schedule_context(1)
        return next(row for row in schedules.get_calls_missing_verified_time(
            reference_time_utc=self.now, days_ahead=2) if row['id'] == 1)

    def test_actual_targeted_repository_retains_clock_proof_and_conflicts_through_enricher(self):
        self._assert_repository_enrichment_sequence('targeted')

    def test_actual_batch_repository_retains_clock_proof_and_conflicts_through_enricher(self):
        self._assert_repository_enrichment_sequence('batch')

    def _assert_repository_enrichment_sequence(self, mode):
        context = self._repository_context(mode)
        for field in ('schedule_discovery_checked_at', 'schedule_discovery_fingerprint',
                      'schedule_evidence', 'source_timezone', 'schedule_revalidation_evidence'):
            self.assertIn(field, context, field)
            self.assertEqual(context[field], self.good[field], field)
        # No hand-built enrichment row: use exactly the public repository output.
        self.assertIsNone(self.run_pages(self.unavailable_issuer(self.provider()), call=context))
        first = self.row()
        self.assertIsNone(first['scheduled_at_utc'])
        self.assertEqual(first['schedule_revalidation_status'], 'provisional_watch')
        self.assertEqual(first['schedule_discovery_checked_at'], self.good['schedule_discovery_checked_at'])
        clocks = json.loads(first['schedule_revalidation_evidence'])['clock_observations']
        self.assertEqual(next(x['source_timezone'] for x in clocks if x['source'] == fixture.DETAIL),
                         self.good['source_timezone'])
        self.now += timedelta(minutes=31)
        context = self._repository_context(mode)
        self.assertEqual(json.loads(context['schedule_revalidation_evidence'])['clock_observations'], clocks)
        # Fresh issuer clock alone cannot erase the conflicting provider clock.
        self.assertIsNone(self.run_pages({**self.pages, fixture.PROVIDER: None}, call=context))
        self.assertIsNone(self.row()['scheduled_at_utc'])
        self.now += timedelta(minutes=31)
        context = self._repository_context(mode)
        # Nor can the opposite side resolve the unavailable issuer clock.
        self.assertIsNone(self.run_pages(self.unavailable_issuer(self.provider()), call=context))
        self.assertIsNone(self.row()['scheduled_at_utc'])
