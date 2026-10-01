"""Clock ambiguity may not strand an independently verified same-event route."""
from datetime import datetime, timedelta, timezone
import json
import unittest

from data_pipeline.collectors.schedules.event_routes import route_proof
from data_pipeline.stt_worker.manager import STTWorkerManager


class ClockUncertainRouteProofTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.call = dict(
            id=600, ticker='TEST', earning_at=self.now.date(), webcast_date=self.now.date(),
            scheduled_at_utc=None, schedule_revision=4,
            ir_url='https://issuer.test/investors/',
            event_url='https://issuer.test/event/q3/',
            webcast_url='https://provider.test/event/123',
            schedule_source='official_ir_stored_event_discovery',
            schedule_discovery_fingerprint='a' * 64,
            schedule_discovery_checked_at=self.now,
            schedule_revalidation_status='provisional_watch',
            schedule_revalidation_reason='ambiguous_call_time',
            schedule_revalidation_evidence=json.dumps(dict(
                conflict_kind='start_time_conflict', route_identity_verified=True)),
            verified_fiscal_year=2026, verified_fiscal_quarter='Q3',
        )
        self.call['schedule_evidence'] = route_proof(
            ticker='TEST', day=self.now.date(), issuer_url=self.call['ir_url'],
            event_url=self.call['event_url'], webcast_url=self.call['webcast_url'],
            fiscal_year=2026, fiscal_quarter='Q3') + ' Q3 2026 Earnings Call'

    def test_exact_clock_uncertainty_does_not_block_bound_route_handoff(self):
        proof = STTWorkerManager._stored_target_proof(self.call)
        self.assertIsNotNone(proof)
        self.assertEqual(proof['target_url'], self.call['webcast_url'])
        self.call.update(_live_entrypoint_kind='webcast_url',
                         _live_entrypoint_url=self.call['webcast_url'])
        runtime = STTWorkerManager._probe_runtime_environment(self.call, {})
        self.assertEqual(runtime['WEBCAST_LIVE_ENTRYPOINT_VERIFIED'], 'true')
        self.assertIsNone(self.call['scheduled_at_utc'])

    def test_date_identity_ambiguity_and_cancelled_events_remain_untrusted(self):
        for status, reason in (
            ('provisional_watch', 'ambiguous_event_identity'),
            ('provisional_watch', 'date_mismatch'),
            ('cancelled', 'official_cancelled'),
            ('provisional_watch', 'official_postponed'),
        ):
            with self.subTest(reason=reason):
                call = {**self.call, 'schedule_revalidation_status': status,
                        'schedule_revalidation_reason': reason}
                self.assertIsNone(STTWorkerManager._stored_target_proof(call))

    def test_legacy_ambiguity_without_explicit_route_classification_is_not_trusted(self):
        for evidence in (None, '', 'invalid JSON', '{}', '[]',
                         '{"conflict_kind":"event_date_conflict","route_identity_verified":true}',
                         '{"conflict_kind":"start_time_conflict","route_identity_verified":false}'):
            with self.subTest(evidence=evidence):
                self.assertIsNone(STTWorkerManager._stored_target_proof(
                    {**self.call, 'schedule_revalidation_evidence': evidence}))

    def test_marker_does_not_bypass_route_age_or_identity_checks(self):
        for changes in (
            {'schedule_discovery_checked_at': self.now - timedelta(hours=7)},
            {'schedule_discovery_checked_at': self.now + timedelta(minutes=1)},
            {'ticker': 'OTHER'},
            {'webcast_date': self.now.date() + timedelta(days=1)},
            {'verified_fiscal_quarter': 'Q2'},
            {'ir_url': 'https://unrelated.test/events/'},
            {'schedule_discovery_fingerprint': None},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(STTWorkerManager._stored_target_proof({**self.call, **changes}))

    def test_retained_source_timestamp_cannot_be_laundered_by_fresh_clock(self):
        evidence = self.call['schedule_evidence']
        prefix, rest = evidence.split(':', 1)
        decoder = json.JSONDecoder()
        payload, stop = decoder.raw_decode(rest)
        payload['source_observed_at'] = (self.now - timedelta(hours=7)).isoformat()
        call = {**self.call, 'schedule_evidence': prefix + ':' + json.dumps(payload) + rest[stop:]}
        self.assertIsNone(STTWorkerManager._stored_target_proof(call))


if __name__ == '__main__':
    unittest.main()
