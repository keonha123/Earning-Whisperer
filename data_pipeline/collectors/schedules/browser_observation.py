"""Share scoped browser clock evidence with the scheduler; never infer a zone."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from .call_times import parse_call_times, seasonal_abbreviation_conflict


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _instant(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def proof_extends_route(previous, current, *, now):
    """Accept only an observed, contiguous IR-to-provider transition chain."""
    from ..streams.browser.navigation import same_event_route
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False
    old_target, target = str(previous.get('target_url') or ''), str(current.get('target_url') or '')
    if previous.get('source_url') != current.get('source_url'):
        return False
    if same_event_route(old_target, target):
        return True
    old_source_at = _instant(previous.get('source_observed_at') or previous.get('observed_at'))
    source_at = _instant(current.get('source_observed_at') or current.get('observed_at'))
    if old_source_at is None or source_at != old_source_at:
        return False
    chain = current.get('route_lineage')
    if not isinstance(chain, list) or not 1 <= len(chain) <= 8:
        return False
    reachable, last_at, began = old_target, source_at, False
    for edge in chain:
        if not isinstance(edge, dict) or edge.get('kind') not in {'selected_link', 'observed_redirect'}:
            return False
        parent, child = edge.get('parent_target_url'), edge.get('target_url')
        for url in (parent, child):
            from .clock_reconciliation import source_key
            if not source_key(url):
                return False
        at = _instant(edge.get('observed_at'))
        if at is None or at < last_at or not -5 <= (now - at).total_seconds() <= 21600:
            return False
        last_at = at
        if not began:
            if same_event_route(reachable, parent):
                began = True
            else:
                continue
        if not same_event_route(reachable, parent):
            return False
        reachable = child
    return began and same_event_route(reachable, target)


def _provider_scope(proof, evidence_url):
    from ..streams.browser.navigation import provider_event_id, same_event_route
    from ..streams.browser.rules import is_webcast_player_url
    target = str(proof.get('target_url') or '')
    return bool(same_event_route(target, evidence_url or '')
                and (provider_event_id(target) or is_webcast_player_url(target)))


def observe_browser_time(agent, evidence: str, *, evidence_url: str | None = None):
    """Called only for a selected event row or its validated provider page."""
    if getattr(agent, 'lifecycle', None) != 'live':
        return None
    from ..streams.browser.navigation import proof_is_fresh
    proof = getattr(agent, 'live_target_proof', None)
    if not proof_is_fresh(agent, proof) or not getattr(agent, 'target_date', None):
        return None
    target_period = dict(expected_fiscal_year=getattr(agent, 'target_year', None),
                         expected_fiscal_quarter=getattr(agent, 'target_quarter', None))
    parsed = parse_call_times(evidence, agent.target_date, grace_days=0,
                              authenticated_provider=_provider_scope(proof, evidence_url), **target_period)
    selected = parsed.selected
    if selected is None:
        if parsed.conflicted or parsed.unavailable_reason:
            agent.schedule_observation = None
            from ...live_telemetry import emit_live_event
            emit_live_event('schedule', 'browser_start_ambiguous', status='unverified', observation=None)
        return None
    previous = getattr(agent, 'schedule_observation', None)
    observation = {
        'webcast_date': selected.webcast_date.isoformat(),
        'scheduled_at_utc': selected.scheduled_at_utc.isoformat(),
        'source_timezone': selected.source_timezone,
        'schedule_evidence': selected.evidence,
        'evidence_url': evidence_url or proof['source_url'],
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'identity_proof': dict(proof),
    }
    # Preserve the readings even if the browser prefers one for navigation.
    # The common DB writer, not this process's last page, resolves disagreement.
    readings = list(getattr(agent, 'schedule_clock_observations', []))
    readings = [item for item in readings if item.get('evidence_url') != observation['evidence_url']]
    readings.append(dict(observation))
    agent.schedule_clock_observations = readings[-12:]
    observation['clock_observations'] = list(agent.schedule_clock_observations)
    # A selected IR card may use a year-round CST/EST label while the verified
    # provider/DB clock already establishes the DST instant. Retain that proof
    # and emit a disagreement, rather than letting a fallback delay capture.
    targets = [getattr(agent, 'target_time_utc', None)]
    if isinstance(previous, dict):
        targets.append(_instant(previous.get('scheduled_at_utc')))
    if any(seasonal_abbreviation_conflict(selected, target) for target in targets):
        from ...live_telemetry import emit_live_event
        emit_live_event('schedule', 'browser_start_timezone_conflict', status='unverified',
                        observation=previous, evidence=selected.evidence,
                        rejected_scheduled_at_utc=selected.scheduled_at_utc.isoformat())
        if isinstance(previous, dict):
            previous['clock_observations'] = list(agent.schedule_clock_observations)
            agent.schedule_observation = previous
            return previous
        # Keep the contrary reading for the DB consensus rule even when this
        # process has only the previously stored target clock.
    previous_clock = (parse_call_times(str(previous.get('schedule_evidence') or ''), agent.target_date, grace_days=0, **target_period).selected
                      if isinstance(previous, dict) else None)
    replaces_standard_label = bool(previous_clock and
        seasonal_abbreviation_conflict(previous_clock, selected.scheduled_at_utc))
    if (isinstance(previous, dict) and previous.get('evidence_url') != (evidence_url or proof['source_url'])
            and previous.get('scheduled_at_utc') != selected.scheduled_at_utc.isoformat()
            and not replaces_standard_label):
        agent.schedule_observation = observation
        from ...live_telemetry import emit_live_event
        emit_live_event('schedule', 'browser_start_ambiguous', status='unverified', observation=observation)
        return observation
    agent.schedule_observation = observation
    from ...live_telemetry import emit_live_event
    emit_live_event('schedule', 'browser_start_observed', status='verified', progress=True,
                    observation=observation)
    return observation


def browser_clock_changed(call, values):
    current = call.get('scheduled_at_utc')
    if current is None:
        return True
    try:
        current = datetime.fromisoformat(str(current))
        observed = datetime.fromisoformat(str(values['scheduled_at_utc']))
        return current.replace(tzinfo=current.tzinfo or timezone.utc).astimezone(timezone.utc) != observed.replace(tzinfo=observed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return True


def validated_browser_values(call: dict, observation: object, *, now=None, _include_clocks=True):
    """Validate subprocess evidence again before it can reach the DB writer.

    A clock in an error string, an unrelated date or an arbitrary provider URL
    is not proof. Keep the selected event's issuer-to-provider route and exact
    event day. Cross-day rescheduling belongs to official reconciliation.
    """
    if not isinstance(observation, dict):
        return None
    proof = observation.get('identity_proof')
    if not isinstance(proof, dict) or proof.get('verified') is not True:
        return None
    expected = _day(call.get('webcast_date') or call.get('earning_at'))
    if not expected or _day(proof.get('target_date')) != expected:
        return None
    if str(proof.get('call_ticker') or '').upper() != str(call.get('ticker') or '').upper():
        return None
    now = now or datetime.now(timezone.utc)
    observed, proved = _instant(observation.get('observed_at')), _instant(proof.get('observed_at'))
    source_observed = _instant(proof.get('source_observed_at') or proof.get('observed_at'))
    if any(value is None or not -5 <= (now - value).total_seconds() <= 21600
           for value in (observed, proved, source_observed)):
        return None
    for field, expected_value in (('call_id', call.get('id')), ('schedule_revision', int(call.get('schedule_revision') or 0))):
        for bound in (observation, proof):
            if field in bound and str(bound[field]) != str(expected_value):
                return None
    issuer = urlparse(str(call.get('_issuer_ir_url') or call.get('ir_url') or ''))
    source = urlparse(str(proof.get('source_url') or ''))
    target_url = proof.get('target_url')
    if not isinstance(target_url, str):
        return None
    evidence_url = str(observation.get('evidence_url') or '')
    if (not issuer.hostname or source.hostname != issuer.hostname or source.scheme not in {'http', 'https'}
            or source.username or source.password):
        return None
    from ..streams.browser.navigation import same_event_route
    active_proof = call.get('_live_discovery_proof')
    if (isinstance(active_proof, dict) and active_proof.get('target_url')
            and not proof_extends_route(active_proof, proof, now=now)):
        return None
    # Redirects not proven in this payload are deliberately rechecked by the
    # official enricher; a shared hostname alone is insufficient for providers.
    if evidence_url != proof.get('source_url') and not same_event_route(target_url, evidence_url):
        return None
    parsed_target = urlparse(target_url)
    if parsed_target.scheme not in {'http', 'https'} or not parsed_target.hostname or parsed_target.username or parsed_target.password:
        return None
    parsed = parse_call_times(str(observation.get('schedule_evidence') or ''), expected, grace_days=0,
        expected_fiscal_year=call.get('verified_fiscal_year'),
        expected_fiscal_quarter=call.get('verified_fiscal_quarter'),
        authenticated_provider=_provider_scope(proof, evidence_url))
    selected = parsed.selected
    if (selected is None or _day(observation.get('webcast_date')) != expected
            or selected.scheduled_at_utc != _instant(observation.get('scheduled_at_utc'))
            or selected.source_timezone != observation.get('source_timezone')):
        return None
    from .event_routes import fiscal_period, period_mismatch, route_proof, PROOF_PREFIX
    if period_mismatch(call, str(proof.get('evidence') or '') + ' ' + selected.evidence):
        return None
    year, quarter = fiscal_period(str(proof.get('evidence') or '') + ' ' + selected.evidence)
    event_url = call.get('event_url') or proof['source_url']
    # Retain the exact issuer -> event route alongside the clock. Otherwise a
    # successful time update invalidates the route fingerprint and forces a
    # protected IR page to authenticate the already-proven provider again.
    from ..streams.browser.navigation import provider_event_id
    target_kind = proof.get('target_kind') or ('provider' if provider_event_id(target_url) else 'unknown')
    is_playback_route = target_kind in {'provider', 'player'}
    if target_kind == 'event_detail' or target_url == proof['source_url']:
        event_url = target_url
        is_playback_route = False
    route = route_proof(ticker=call['ticker'], day=expected,
                        issuer_url=proof['source_url'], event_url=None,
                        webcast_url=target_url if is_playback_route else None,
                        fiscal_year=call.get('verified_fiscal_year') or year,
                        fiscal_quarter=call.get('verified_fiscal_quarter') or quarter)
    route_data = json.loads(route.removeprefix(PROOF_PREFIX))
    # A new provider clock cannot refresh the age of the issuer's link proof.
    # Nor can it authenticate a pre-existing event_url (e.g. an earnings release)
    # which was not the selected target of this proof.
    route_data['source_observed_at'] = source_observed.isoformat()
    route = PROOF_PREFIX + json.dumps(route_data, separators=(',', ':'), sort_keys=True)
    fingerprint = hashlib.sha256(json.dumps([expected.isoformat(), event_url,
        target_url, call.get('verified_fiscal_year') or year,
        call.get('verified_fiscal_quarter') or quarter], sort_keys=True).encode()).hexdigest()
    provider = urlparse(evidence_url).hostname != issuer.hostname
    result = {
        'webcast_date': selected.webcast_date,
        'scheduled_at_utc': selected.scheduled_at_utc.replace(tzinfo=None),
        'source_timezone': selected.source_timezone,
        'schedule_source': 'official_browser_provider' if provider else 'official_browser_event',
        'schedule_evidence': route + ' ' + selected.evidence,
        'event_url': event_url,
        'webcast_url': target_url if is_playback_route else None,
        **({'schedule_discovery_fingerprint': fingerprint,
            'route_observed_at': source_observed.replace(tzinfo=None)} if is_playback_route else {}),
        'observed_at': observed.replace(tzinfo=None),
        'expected_revision': int(call.get('schedule_revision') or 0),
    }
    fact = {'source': evidence_url, 'value': selected.scheduled_at_utc.isoformat(),
            'source_timezone': selected.source_timezone, 'evidence': selected.evidence,
            'observed_at': observed.isoformat()}
    result['clock_observations'] = [fact]
    if _include_clocks and isinstance(observation.get('clock_observations'), list):
        for earlier in observation['clock_observations'][:12]:
            if not isinstance(earlier, dict):
                return None
            earlier_proof = earlier.get('identity_proof')
            if not (isinstance(earlier_proof, dict)
                    and earlier_proof.get('source_url') == proof.get('source_url')
                    and (same_event_route(str(earlier_proof.get('target_url') or ''), target_url)
                         or proof_extends_route(earlier_proof, proof, now=now))):
                return None
            value = validated_browser_values({**call, '_live_discovery_proof': None}, earlier,
                                             now=now, _include_clocks=False)
            if value is None:
                return None
            result['clock_observations'].extend(value['clock_observations'])
    return result
