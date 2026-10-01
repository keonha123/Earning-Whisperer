"""GIS URL corruption and COST cross-route loss, with no external registration."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from data_pipeline import live_runtime
from data_pipeline.collectors.schedules.browser_observation import observe_browser_time, validated_browser_values
from data_pipeline.collectors.schedules.event_routes import read_route_proof
from data_pipeline.stt_worker.manager import STTWorkerManager, WebcastProbeResult
from data_pipeline.tests.test_browser_schedule_observation import fixture, TEXT
from data_pipeline.tests import test_browser_schedule_storage as storage_fixture


class ClockRouteValueTest(unittest.TestCase):
    def test_existing_datetime_never_replaces_target_url(self):
        for clock in (None, datetime(2026, 9, 23, 14, 30), '2026-09-23 14:30:00',
                      datetime(2026, 9, 23, 14, 30, tzinfo=timezone.utc), 'invalid-clock'):
            with self.subTest(clock=clock):
                agent, call = fixture()
                call['scheduled_at_utc'] = clock
                observation = observe_browser_time(agent, TEXT)
                values = validated_browser_values(call, observation)
                self.assertIsInstance(values['webcast_url'], str)
                self.assertEqual(values['webcast_url'], agent.live_target_proof['target_url'])
                self.assertEqual(values['scheduled_at_utc'], datetime(2026, 9, 23, 14, 30))

    def test_clock_commit_carries_route_proof_across_new_revision(self):
        agent, call = fixture()
        values = validated_browser_values(call, observe_browser_time(agent, TEXT))
        self.assertEqual(read_route_proof(values['schedule_evidence'])['webcast_url'], values['webcast_url'])
        saved = {**call, **values, 'schedule_revision': 3, 'schedule_revalidation_status': 'clear',
                 'schedule_discovery_checked_at': datetime.now(timezone.utc)}
        proof = STTWorkerManager._stored_target_proof(saved)
        self.assertEqual(proof['target_url'], agent.live_target_proof['target_url'])
        self.assertEqual(proof['schedule_revision'], 3)
        self.assertIsNone(STTWorkerManager._stored_target_proof({**saved, 'webcast_date': '2026-09-24'}))

    def test_provider_clock_never_authenticates_unproven_results_page(self):
        agent, call = fixture()
        call['event_url'] = 'https://issuer.test/events/q4-results'
        values = validated_browser_values(call, observe_browser_time(agent, TEXT))
        route = read_route_proof(values['schedule_evidence'])
        self.assertEqual(values['event_url'], call['event_url'])
        self.assertIsNone(route['event_url'])
        saved = {**call, **values, 'schedule_revision': 3, 'schedule_revalidation_status': 'clear',
                 'schedule_discovery_checked_at': datetime.now(timezone.utc)}
        self.assertEqual(STTWorkerManager._stored_target_proof(saved)['target_url'], agent.live_target_proof['target_url'])
        for missing in (None, 'https://app.webinar.net/Other123'):
            self.assertIsNone(STTWorkerManager._stored_target_proof({**saved, 'webcast_url': missing}))

    def test_provider_clock_refresh_cannot_extend_original_issuer_proof_ttl(self):
        agent, call = fixture()
        now = datetime.now(timezone.utc)
        source_observed = now - timedelta(hours=5)
        agent.live_target_proof['source_observed_at'] = source_observed.isoformat()
        observation = observe_browser_time(agent, TEXT)
        values = validated_browser_values(call, observation)
        self.assertEqual(read_route_proof(values['schedule_evidence'])['source_observed_at'], source_observed.isoformat())
        saved = {**call, **values, 'schedule_revision': 3, 'schedule_revalidation_status': 'clear',
                 'schedule_discovery_checked_at': now}
        proof = STTWorkerManager._stored_target_proof(saved)
        self.assertEqual(proof['source_observed_at'], source_observed.isoformat())
        later = now + timedelta(hours=2)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return later.astimezone(tz) if tz else later.replace(tzinfo=None)
        from data_pipeline.stt_worker import manager as manager_module
        with patch.object(manager_module, 'datetime', Clock):
            # Even a freshly updated DB checked_at cannot extend issuer proof.
            self.assertIsNone(STTWorkerManager._stored_target_proof({**saved, 'schedule_discovery_checked_at': later.isoformat()}))
        reobserved = {**observation, 'observed_at': later.isoformat(),
                      'identity_proof': {**proof, 'observed_at': later.isoformat(), 'schedule_revision': call['schedule_revision']}}
        self.assertIsNone(validated_browser_values(call, reobserved, now=later))

    def test_clock_payload_rejects_wrong_bound_revision_call_and_fiscal_period(self):
        for change in ({'call_id': 5}, {'schedule_revision': 1}):
            agent, call = fixture()
            observed = observe_browser_time(agent, TEXT)
            self.assertIsNone(validated_browser_values(call, {**observed, **change}))
            self.assertIsNone(validated_browser_values(call, {**observed,
                'identity_proof': {**observed['identity_proof'], **change}}))
        agent, call = fixture()
        observed = observe_browser_time(agent, TEXT)
        call.update(verified_fiscal_year=2026, verified_fiscal_quarter='Q3')
        self.assertIsNone(validated_browser_values(call, observed))


class ClockURLStorageGuardTest(unittest.TestCase):
    # Reuse real SQL fixture methods without rerunning its entire suite here.
    setUp = storage_fixture.BrowserScheduleStorageTest.setUp
    row = storage_fixture.BrowserScheduleStorageTest.row
    update = storage_fixture.BrowserScheduleStorageTest.update
    evidence = storage_fixture.BrowserScheduleStorageTest.evidence
    finish = storage_fixture.BrowserScheduleStorageTest.finish
    history_count = storage_fixture.BrowserScheduleStorageTest.history_count

    def test_bad_route_types_and_non_http_values_never_poison_database(self):
        before = self.row()
        for bad in (datetime(2035, 9, 22, 14), '2035-09-22 14:00:00+00:00',
                    'javascript:alert(1)', '//provider.test/current', '/current', 123,
                    'https://user:password@provider.test/current', 'https://provider.test:bad/current',
                    'https://provider.test:0/current', 'https://provider.test:65536/current',
                    'https://provider.test:-1/current', 'https://provider.test/white space',
                    'https://provider.test\\@other.test/current', ''):
            for field in ('webcast_url', 'event_url'):
                with self.subTest(field=field, bad=bad):
                    self.update(**before)
                    result = self.finish(ready=True, evidence=self.evidence(**{field: bad}))
                    self.assertFalse(result['schedule_applied'])
                    self.assertFalse(result['capture_handoff_valid'])
                    self.assertEqual(self.row()['webcast_url'], before['webcast_url'])
                    self.assertEqual(self.row()['event_url'], before['event_url'])
                    self.assertEqual(self.row()['schedule_revision'], before['schedule_revision'])
        self.assertEqual(self.history_count(), 0)

    def test_valid_absolute_route_and_clock_commit_together(self):
        before = self.row()
        for route in ('https://provider.test:443/current?event=42',
                      'https://provider.test:8443/current?event=42',
                      'http://127.0.0.1:49152/current?event=42'):
            with self.subTest(route=route):
                self.update(**before)
                result = self.finish(evidence=self.evidence(webcast_url=route))
                self.assertTrue(result['schedule_applied'])
                self.assertEqual(self.row()['webcast_url'], route)
                self.assertEqual(self.row()['scheduled_at_utc'], '2035-09-22 14:00:00')

    def test_browser_clock_update_remains_a_verified_provider_route_after_sql_commit(self):
        from data_pipeline.collectors.schedules import browser_observation
        from data_pipeline.collectors.streams.browser import navigation
        from data_pipeline.stt_worker import manager as manager_module
        text = 'TEST Q4 2035 earnings conference call September 22, 2035 at 10:30 AM EDT'
        proof = dict(verified=True, call_ticker='TEST', target_date=self.now.date().isoformat(),
            source_url='https://issuer.test/event', target_url='https://provider.test/123',
            target_kind='provider',
            observed_at=self.now.replace(tzinfo=timezone.utc).isoformat(), evidence=text)
        agent = SimpleNamespace(lifecycle='live', ticker='TEST', target_date=self.now.date(), live_target_proof=proof)
        self.update(scheduled_at_utc=self.now + timedelta(hours=2))
        call = {**self.row(), 'ir_url': 'https://issuer.test/events'}
        with patch.object(browser_observation, 'datetime', self.clock), \
                patch.object(navigation, 'datetime', self.clock), \
                patch.object(manager_module, 'datetime', self.clock):
            observation = observe_browser_time(agent, text)
            values = validated_browser_values(call, observation)
            result = self.finish(evidence=values)
            saved = {**self.row(), 'ir_url': call['ir_url']}
            reused = STTWorkerManager._stored_target_proof(saved)
        self.assertTrue(result['schedule_applied'])
        self.assertEqual(saved['webcast_url'], proof['target_url'])
        self.assertEqual(saved['schedule_revision'], 8)
        self.assertEqual(reused['target_url'], proof['target_url'])
        self.assertEqual(reused['schedule_revision'], 8)


class CrossRouteClockRecoveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for context in (patch.object(live_runtime, 'runtime_root', return_value=self.root),
                        patch.dict(os.environ, {'WEBCAST_CAPTURE_RUNNER': 'container',
                            'DATE_STREAM_CANDIDATE_RETRY_DELAY_SECONDS': '0'})):
            context.start(); self.addCleanup(context.stop)
        agent, self.call = fixture()
        self.call.update(webcast_url=agent.live_target_proof['target_url'],
                         _live_discovery_proof=agent.live_target_proof)
        self.observation = observe_browser_time(agent, TEXT, evidence_url=agent.live_target_proof['target_url'])
        live_runtime.prepare_attempt(self.call)
        self.manager = STTWorkerManager()

    def snapshot(self, observation=None):
        return {'schedule_revision': self.call['schedule_revision'], 'attempt_id': self.call['_live_attempt_id'],
                'call_id': self.call['id'], 'observation': observation or self.observation,
                'event': 'browser_start_observed'}

    async def fail_provider_then_ir(self):
        seen = []
        async def probe(route, **kwargs):
            first = not seen
            seen.append(route['ir_url'])
            return WebcastProbeResult(False,
                'FORM_AUTOMATION_FAILED form validation failed' if first else 'page access blocked: CAPTCHA', '', 1,
                {'WEBCAST_LIVE_ENTRYPOINT_VERIFIED': 'true' if first else 'false'})
        with patch.object(self.manager, 'probe_webcast_url_detailed', side_effect=probe), \
                patch.object(self.manager, '_probe_heartbeat_loop', new_callable=AsyncMock), \
                patch('data_pipeline.stt_worker.manager.read_progress_snapshot', return_value={'schedule': self.snapshot()}):
            result = await self.manager.probe_date_based_call(self.call, capture_env={})
        return result, seen

    async def test_cost_valid_clock_survives_unverified_ir_failure(self):
        result, seen = await self.fail_provider_then_ir()
        self.assertFalse(result[0])
        self.assertEqual(seen[0], self.call['webcast_url'])
        saved = self.call['_browser_schedule_observation']
        self.assertEqual(saved['scheduled_at_utc'], self.observation['scheduled_at_utc'])
        self.assertEqual(saved['schedule_revision'], self.call['schedule_revision'])
        self.assertIsNotNone(validated_browser_values(self.call, saved))
        log = (Path(self.call['_live_progress_dir']) / 'events.jsonl').read_text()
        self.assertIn('browser_clock_retained', log)
        self.assertIn('FORM_AUTOMATION_FAILED', log)
        self.assertIn('AUTH_REQUIRED', log)

    async def test_next_watch_retries_verified_provider_when_ir_is_cooled_down(self):
        await self.fail_provider_then_ir()
        next_call = {key: value for key, value in self.call.items() if not key.startswith('_')}
        manager = STTWorkerManager()
        with patch('data_pipeline.stt_worker.manager.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            result = await manager.discover_date_based_call(next_call)
        spawn.assert_not_awaited()
        self.assertTrue(result['target_identity_verified'])
        self.assertEqual(result['discovered_url'], self.call['webcast_url'])
        next_call['_live_discovery_proof'] = result['identity_proof']
        calls = []
        async def probe(route, **kwargs):
            calls.append(route['ir_url'])
            env = manager._probe_runtime_environment(route, kwargs['capture_env'])
            self.assertEqual(json.loads(env['WEBCAST_LIVE_IDENTITY_PROOF'])['target_url'], self.call['webcast_url'])
            return WebcastProbeResult(False, 'NOT_LIVE_YET verified event waiting', '', 1, env)
        with patch.object(manager, 'probe_webcast_url_detailed', side_effect=probe), \
                patch.object(manager, '_probe_heartbeat_loop', new_callable=AsyncMock):
            await manager.probe_date_based_call(next_call, capture_env={})
        self.assertEqual(calls, [self.call['webcast_url']])

    async def test_provider_authentication_barrier_itself_is_never_bypassed(self):
        await self.fail_provider_then_ir()
        self.manager._cooldown_failed_entrypoint(self.call, 'webcast_url', self.call['webcast_url'], 'AUTH_REQUIRED email verification')
        with patch('data_pipeline.stt_worker.manager.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            result = await STTWorkerManager().discover_date_based_call(self.call)
        self.assertFalse(result['target_identity_verified'])
        spawn.assert_not_awaited()

    def test_remembered_route_requires_revision_date_call_event_id_and_freshness(self):
        proof = self.manager._remember_target_proof(self.call, self.observation['identity_proof'])
        self.assertIsNotNone(self.manager._remembered_target_proof(self.call))
        for change in ({'schedule_revision': 3}, {'webcast_date': '2026-09-24'}, {'id': 2},
                       {'ticker': 'OTHER'}, {'schedule_discovery_fingerprint': 'new'}):
            with self.subTest(change=change):
                self.assertIsNone(self.manager._remembered_target_proof({**self.call, **change}))
        for change in ({'provider_event_id': 'webinar:Wrong123'}, {'source_url': 'https://other.test/event'},
                       {'observed_at': (datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()},
                       {'source_observed_at': (datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()},
                       {'schedule_revision': 99}):
            with self.subTest(change=change):
                live_runtime.remember_verified_route(self.call, {**proof, **change})
                self.assertIsNone(self.manager._remembered_target_proof(self.call))

    def test_valid_http_custom_ports_preserve_event_proof_checks(self):
        for issuer, target in (('https://issuer.test:8443/events', 'https://provider.test:9443/event-123'),
                               ('http://127.0.0.1:49152/ir', 'http://127.0.0.1:49152/live')):
            with self.subTest(issuer=issuer, target=target):
                call = {**self.call, 'ir_url': issuer}
                proof = {**self.observation['identity_proof'], 'source_url': issuer, 'target_url': target}
                self.assertTrue(self.manager._fresh_discovery_proof(call, target, proof))
                self.assertFalse(self.manager._fresh_discovery_proof(call, target, {**proof, 'target_date': '2026-09-24'}))
                self.assertFalse(self.manager._fresh_discovery_proof(call, target, {**proof, 'call_ticker': 'OTHER'}))
                self.assertFalse(self.manager._fresh_discovery_proof(call, target, {**proof, 'source_url': 'https://other.test:8443/ir'}))

    def test_invalid_or_zero_route_ports_never_authenticate(self):
        for port in ('bad', '0', '-1', '65536'):
            for field in ('source_url', 'target_url'):
                proof = {**self.observation['identity_proof']}
                host = 'issuer.test' if field == 'source_url' else 'provider.test'
                proof[field] = f'https://{host}:{port}/event'
                self.assertFalse(self.manager._fresh_discovery_proof(self.call, proof['target_url'], proof))

    def test_unverified_url_or_boolean_signal_cannot_create_route_proof(self):
        self.assertIsNone(self.manager._remembered_target_proof(self.call))
        self.assertIsNone(self.manager._remember_target_proof(self.call, {'verified': True, 'target_url': self.call['webcast_url']}))
        self.assertIsNone(self.manager._remembered_target_proof(self.call))

    def test_missing_or_foreign_observation_does_not_replace_a_valid_clock(self):
        retain = self.manager._retain_browser_observation
        retain(self.call, self.observation, identity_verified=True, route_url=self.call['webcast_url'])
        previous = self.call['_browser_schedule_observation']
        for incoming in (None, {**self.observation, 'schedule_revision': 99},
                         {**self.observation, 'identity_proof': {**self.observation['identity_proof'], 'call_ticker': 'OTHER'}}):
            retain(self.call, incoming, identity_verified=True, route_url=self.call['ir_url'])
            self.assertEqual(self.call['_browser_schedule_observation'], previous)

    def test_conflicting_same_event_sources_are_not_last_writer_wins(self):
        self.manager._retain_browser_observation(self.call, self.observation, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        agent, _ = fixture()
        conflicting = observe_browser_time(agent, TEXT.replace('10:30', '11:30'))
        self.manager._retain_browser_observation(self.call, conflicting, identity_verified=True,
                                                route_url=self.call['event_url'])
        saved = self.call['_browser_schedule_observation']
        values = validated_browser_values(self.call, saved)
        readings = {(row['source'], row['value']) for row in values['clock_observations']}
        self.assertIn((self.call['webcast_url'], self.observation['scheduled_at_utc']), readings)
        self.assertIn((self.call['event_url'], conflicting['scheduled_at_utc']), readings)
        self.assertTrue(self.call['_browser_schedule_conflict'])
        self.assertTrue(all('clock_observations' not in row for row in saved['clock_observations']))

    def test_conflicting_bundle_reaches_the_common_probe_writer(self):
        from data_pipeline.application.live_watch import LiveWatchService
        from unittest.mock import Mock
        self.test_conflicting_same_event_sources_are_not_last_writer_wins()
        repository = Mock()
        repository.record_stream_probe.return_value = {'accepted': True, 'schedule_conflicted': True}
        watcher = LiveWatchService(repository, self.manager, Mock(), Mock())
        watcher._record_probe(self.call['id'], call=self.call,
                              stream_ready=False, error='FORM_AUTOMATION_FAILED')
        passed = repository.record_stream_probe.call_args.kwargs['schedule_observation']
        self.assertEqual({row['value'] for row in passed['clock_observations']},
                         {'2026-09-23T14:30:00+00:00', '2026-09-23T15:30:00+00:00'})

    def test_later_unverified_route_cannot_erase_pending_clock_conflict(self):
        self.test_conflicting_same_event_sources_are_not_last_writer_wins()
        saved = self.call['_browser_schedule_observation']
        self.manager._retain_browser_observation(self.call, None, identity_verified=False,
                                                route_url='https://unrelated.test/event')
        self.assertEqual(self.call['_browser_schedule_observation'], saved)
        self.assertTrue(self.call['_browser_schedule_conflict'])

    def test_unverified_nested_clock_cannot_contaminate_valid_previous_reading(self):
        self.manager._retain_browser_observation(self.call, self.observation, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        saved = self.call['_browser_schedule_observation']
        foreign = {**self.observation, 'identity_proof': {
            **self.observation['identity_proof'], 'call_ticker': 'OTHER'}}
        incoming = {**self.observation, 'clock_observations': [foreign]}
        self.manager._retain_browser_observation(self.call, incoming, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        self.assertEqual(self.call['_browser_schedule_observation'], saved)

    def test_older_same_source_cannot_revert_latest_preferred_clock(self):
        agent, _ = fixture()
        fresh = observe_browser_time(agent, TEXT.replace('10:30', '11:30'),
                                     evidence_url=self.call['webcast_url'])
        self.manager._retain_browser_observation(self.call, fresh, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        older = {**self.observation, 'observed_at':
            (datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(), 'clock_observations': []}
        self.manager._retain_browser_observation(self.call, older, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        values = validated_browser_values(self.call, self.call['_browser_schedule_observation'])
        self.assertEqual(values['scheduled_at_utc'], datetime(2026, 9, 23, 15, 30))
        self.assertFalse(self.call['_browser_schedule_conflict'])

    def test_authenticated_route_extension_keeps_ancestor_clock_for_writer(self):
        agent, _ = fixture()
        source = agent.live_target_proof['source_url']
        initial = {**agent.live_target_proof, 'target_url': source, 'target_kind': 'event_detail'}
        agent.live_target_proof = initial
        self.call['_live_discovery_proof'] = initial
        first = observe_browser_time(agent, TEXT, evidence_url=source)
        self.manager._retain_browser_observation(self.call, first, identity_verified=True, route_url=source)
        provider = {**initial, 'target_url': self.call['webcast_url'], 'target_kind': 'provider',
            'source_observed_at': initial['observed_at'], 'route_lineage': [{
                'kind': 'selected_link', 'parent_target_url': source,
                'target_url': self.call['webcast_url'], 'observed_at': datetime.now(timezone.utc).isoformat()}]}
        later_agent, _ = fixture()
        later_agent.live_target_proof = provider
        later = observe_browser_time(later_agent, TEXT.replace('10:30', '11:30'),
                                     evidence_url=self.call['webcast_url'])
        # Rediscovery has already advanced the active proof. The ancestor is
        # no longer valid on its own, but is valid inside this proven lineage.
        self.call['_live_discovery_proof'] = provider
        self.manager._retain_browser_observation(self.call, later, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        values = validated_browser_values(self.call, self.call['_browser_schedule_observation'])
        self.assertEqual({row['source'] for row in values['clock_observations']},
                         {source, self.call['webcast_url']})
        self.assertTrue(self.call['_browser_schedule_conflict'])

    def test_explicit_same_provider_clock_conflict_clears_old_observation(self):
        self.manager._retain_browser_observation(self.call, self.observation, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        self.manager._retain_browser_observation(self.call, None, identity_verified=True,
            route_url=self.call['webcast_url'], event='browser_start_ambiguous')
        self.assertNotIn('_browser_schedule_observation', self.call)

    def test_revision_change_discards_retained_clock(self):
        self.manager._retain_browser_observation(self.call, self.observation, identity_verified=True,
                                                route_url=self.call['webcast_url'])
        self.call['schedule_revision'] += 1
        self.manager._retain_browser_observation(self.call, None, identity_verified=False, route_url=self.call['ir_url'])
        self.assertNotIn('_browser_schedule_observation', self.call)


if __name__ == '__main__':
    unittest.main()
