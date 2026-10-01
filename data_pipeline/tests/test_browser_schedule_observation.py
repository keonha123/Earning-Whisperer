"""Clock evidence must survive browser handoff without weakening event identity."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import unittest

from data_pipeline.collectors.schedules.browser_observation import (
    observe_browser_time, validated_browser_values, browser_clock_changed,
)


DAY = date(2026, 9, 23)
TEXT = 'EXM Q4 2026 earnings conference call September 23, 2026 at 10:30 AM EDT'


def fixture():
    now = datetime.now(timezone.utc)
    proof = dict(verified=True, call_ticker='EXM', target_date=DAY.isoformat(),
                 source_url='https://issuer.test/events/q4',
                 target_url='https://app.webinar.net/Abc123', observed_at=now.isoformat(), evidence=TEXT)
    agent = SimpleNamespace(lifecycle='live', ticker='EXM', target_date=DAY, live_target_proof=proof)
    call = dict(id=1, ticker='EXM', earning_at=DAY, schedule_revision=2,
                ir_url='https://issuer.test/events', event_url='https://issuer.test/events/q4')
    return agent, call


def test_selected_browser_clock_becomes_typed_db_values():
    agent, call = fixture()
    with mock.patch('data_pipeline.live_telemetry.emit_live_event') as emit:
        observed = observe_browser_time(agent, TEXT)
    assert emit.call_args.args[:2] == ('schedule', 'browser_start_observed')
    values = validated_browser_values(call, observed)
    assert values['scheduled_at_utc'] == datetime(2026, 9, 23, 14, 30)
    assert values['source_timezone'] == 'EDT'
    assert values['event_url'] == call['event_url']
    assert values['expected_revision'] == 2
    assert values['schedule_source'] == 'official_browser_event'


def test_provider_clock_retains_issuer_route_and_known_live_transition():
    agent, call = fixture()
    observed = observe_browser_time(agent, TEXT, evidence_url='https://app.webinar.net/Abc123/live')
    assert validated_browser_values(call, observed)['schedule_source'] == 'official_browser_provider'


def test_non_call_zone_missing_wrong_date_and_tbd_are_not_exact_clocks():
    for text in [
        'EXM earnings release September 23, 2026 at 7:00 AM EDT',
        'EXM earnings conference call September 23, 2026 at 10:30 AM',
        'EXM earnings conference call September 24, 2026 at 10:30 AM EDT',
        'EXM earnings conference call September 23, 2026; time to be announced',
    ]:
        agent, _ = fixture()
        assert observe_browser_time(agent, text) is None


def test_release_and_live_qa_are_not_conflated():
    agent, call = fixture()
    evidence = ('EXM prepared remarks published September 23, 2026 at 7:00 AM EDT. '
                'EXM live Q&A session September 23, 2026 at 10:30 AM EDT.')
    assert validated_browser_values(call, observe_browser_time(agent, evidence))['scheduled_at_utc'] == datetime(2026, 9, 23, 14, 30)


def test_conflicting_clock_clears_previous_observation():
    agent, _ = fixture()
    assert observe_browser_time(agent, TEXT)
    assert observe_browser_time(agent, TEXT + '. ' + TEXT.replace('10:30', '11:30')) is None
    assert agent.schedule_observation is None


def test_subprocess_observation_is_revalidated():
    for mutation in [
        lambda o: o['identity_proof'].update(verified=False),
        lambda o: o['identity_proof'].update(call_ticker='OTHER'),
        lambda o: o['identity_proof'].update(target_date='2026-09-24'),
        lambda o: o['identity_proof'].update(source_url='https://unrelated.test/events'),
        lambda o: o.update(evidence_url='https://app.webinar.net/Different'),
        lambda o: o.update(scheduled_at_utc='2026-09-23T16:00:00+00:00'),
        lambda o: o.update(source_timezone='America/Chicago'),
        lambda o: o.update(observed_at=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()),
        lambda o: o.update(observed_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()),
    ]:
        agent, call = fixture()
        observed = observe_browser_time(agent, TEXT)
        mutation(observed)
        assert validated_browser_values(call, observed) is None


def test_exact_clock_comparison_handles_db_naive_and_aware_values():
    _, call = fixture()
    values = {'scheduled_at_utc': datetime(2026, 9, 23, 14, 30)}
    assert browser_clock_changed(call, values)
    for value in [datetime(2026, 9, 23, 14, 30), '2026-09-23 14:30:00', '2026-09-23T14:30:00+00:00']:
        assert not browser_clock_changed({**call, 'scheduled_at_utc': value}, values)


def test_observation_from_previous_target_cannot_update_current_event():
    agent, call = fixture()
    observed = observe_browser_time(agent, TEXT)
    call['_live_discovery_proof'] = {**agent.live_target_proof, 'target_url': 'https://app.webinar.net/Other123'}
    assert validated_browser_values(call, observed) is None


def test_provider_and_issuer_clock_disagreement_is_not_last_writer_wins():
    agent, _ = fixture()
    assert observe_browser_time(agent, TEXT)
    observation = observe_browser_time(agent, TEXT.replace('10:30', '11:30'), evidence_url=agent.live_target_proof['target_url'])
    assert len(observation['clock_observations']) == 2
    assert len({x['scheduled_at_utc'] for x in observation['clock_observations']}) == 2


def test_target_reset_clears_previous_observation():
    from data_pipeline.collectors.streams.browser.agent import BrowserWebcastAgent
    agent, _ = fixture()
    assert observe_browser_time(agent, TEXT)
    agent.live_entrypoint_identity_verified = False
    agent._entrypoint_target_proof = None
    agent.target_identity_ready_path = None
    BrowserWebcastAgent._reset_live_target_identity_confirmation(agent)
    assert agent.schedule_observation is None


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name, value in globals().items() if name.startswith("test_") and callable(value))
