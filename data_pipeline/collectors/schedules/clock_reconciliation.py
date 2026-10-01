"""One durable clock-consensus rule for issuer and browser observations.

The adapters authenticate event identity and parse clocks. This module preserves
which source said what; one later observation cannot erase another source's
unresolved contradiction. It never changes route evidence or its lifetime.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlsplit

MAX_CLOCK_SOURCES = 12


def instant(value):
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def source_key(value):
    if not isinstance(value, str) or value != value.strip():
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username or parsed.password or '\\' in value
                or any(c.isspace() or ord(c) < 32 for c in value) or parsed.port == 0):
            return None
    except ValueError:
        return None
    from ..streams.browser.navigation import provider_event_id
    event_id = provider_event_id(value)
    # Canonical guest/live path transitions keep their event ID, but signed
    # query values, authority and fragments remain part of the source identity.
    return '|'.join((parsed.scheme, parsed.netloc.lower(), event_id or parsed.path,
                     parsed.query, parsed.fragment))


def normalize_observations(values):
    result = {}
    if not isinstance(values, list):
        return result
    for item in values[:MAX_CLOCK_SOURCES * 2]:
        if not isinstance(item, dict):
            continue
        key, value = source_key(item.get('source')), instant(item.get('value'))
        if not key or not value:
            continue
        observed = instant(item.get('observed_at') or item.get('source_observed_at'))
        entry = {'source': item['source'], 'value': value.isoformat(),
                 'source_timezone': str(item.get('source_timezone') or '')[:80],
                 'evidence': str(item.get('evidence') or '')[-1000:]}
        if observed:
            entry['observed_at'] = observed.isoformat()
        alternatives = {v.isoformat() for raw in item.get('conflicting_values', [])
                        if (v := instant(raw))} if isinstance(item.get('conflicting_values'), list) else set()
        # An explicitly historical reading is never made fresh by re-saving it.
        if item.get('observation') == 'stored':
            entry['observation'] = 'stored'
        previous = result.get(key)
        if (previous and previous['value'] != entry['value']
                and instant(previous.get('observed_at')) == observed):
            alternatives.update((previous['value'], entry['value']))
            alternatives.update(previous.get('conflicting_values', []))
        if len(alternatives) > 1:
            entry['conflicting_values'] = sorted(alternatives)
        if (previous and instant(previous.get('observed_at')) and
                (not observed or observed < instant(previous['observed_at']))):
            continue
        result[key] = entry
    return result


def read_clock_evidence(row):
    try:
        evidence = row.get('schedule_revalidation_evidence') or {}
        evidence = json.loads(evidence) if isinstance(evidence, str) else evidence
    except (ValueError, TypeError):
        evidence = {}
    return evidence if isinstance(evidence, dict) else {}


def row_clock_observation(row):
    value = instant(row.get('scheduled_at_utc'))
    if (not value or row.get('time_verification_status') != 'verified'
            or not str(row.get('schedule_source') or '').startswith('official')
            or not row.get('schedule_evidence')):
        return None
    source = row.get('webcast_url') if 'provider' in str(row.get('schedule_source')) else row.get('event_url')
    if not source_key(source):
        return None
    observed = instant(row.get('time_verified_at') or row.get('schedule_observed_at'))
    return {'source': source, 'value': value.isoformat(), 'source_timezone': row.get('source_timezone'),
            'evidence': row.get('schedule_evidence'), 'observation': 'stored',
            **({'observed_at': observed.isoformat()} if observed else {})}


def reconcile_clock_observations(row, incoming, *, observed_at, reset_event=False,
                                 freshness_seconds=7200):
    """Merge authenticated readings, retaining conflicts until every side agrees.

    After a conflict each participating source must be re-observed at or after
    its first conflicting observation, within the clock freshness budget. The
    durable timestamp prevents a provider-only retry from resolving an outage.
    A separately authenticated cross-day reschedule starts a new event ledger.
    """
    now = instant(observed_at)
    if now is None:
        raise ValueError('clock reconciliation requires an observation time')
    old_evidence = {} if reset_event else read_clock_evidence(row)
    previous = normalize_observations(old_evidence.get('clock_observations'))
    old_clock = None if reset_event else row_clock_observation(row)
    if old_clock:
        for key, value in normalize_observations([old_clock]).items():
            previous.setdefault(key, value)
    supplied = normalize_observations(incoming)
    current = {key: value for key, value in supplied.items()
               if value.get('observation') != 'stored'
               and instant(value.get('observed_at')) is not None
               and -5 <= (now - instant(value['observed_at'])).total_seconds() <= freshness_seconds}
    merged = dict(previous)
    for key, value in supplied.items():
        old = merged.get(key)
        old_at, new_at = instant((old or {}).get('observed_at')), instant(value.get('observed_at'))
        if not old or (new_at is not None and (old_at is None or new_at >= old_at)):
            merged[key] = value
    was_conflicted = bool(not reset_event and (
        row.get('schedule_revalidation_reason') == 'ambiguous_call_time'
        or old_evidence.get('clock_state') == 'conflicted'))
    required = {key for item in old_evidence.get('required_clock_sources', [])
                if (key := source_key(item))} if isinstance(old_evidence.get('required_clock_sources'), list) else set()
    if was_conflicted:
        required |= set(previous)
    started = instant(old_evidence.get('clock_conflict_started_at'))
    if was_conflicted and started is None:
        started = instant(row.get('schedule_observed_at')) or now
    different = (len({item['value'] for item in merged.values()}) > 1
                 or any(item.get('conflicting_values') for item in merged.values()))
    if different:
        required |= set(merged)
        started = started or now
    missing = []
    if was_conflicted or different:
        for key in required:
            value = merged.get(key)
            at = instant((value or {}).get('observed_at'))
            if (not value or not at or at <= started
                    or not -5 <= (now - at).total_seconds() <= freshness_seconds):
                missing.append((value or previous.get(key) or {}).get('source', key))
    # Unknown legacy conflict sources cannot be cleared by one isolated reading.
    sources_incomplete = bool(old_evidence.get('clock_sources_incomplete')
                              or (was_conflicted and not previous))
    unknown_legacy = sources_incomplete and len(current) < 2
    conflicted = bool(different or (was_conflicted and (missing or unknown_legacy)))
    overflow = len(merged) > MAX_CLOCK_SOURCES
    if overflow:
        conflicted = True
        missing.append('source_budget_exceeded')
    ordered = [merged[key] for key in sorted(merged)[:MAX_CLOCK_SOURCES]]
    evidence = {'clock_validation_version': 1, 'clock_observations': ordered,
                'clock_state': 'conflicted' if conflicted else 'confirmed'}
    if conflicted:
        evidence.update(conflict_kind='start_time_conflict',
            clock_conflict_started_at=(started or now).isoformat(),
            required_clock_sources=sorted({merged[k]['source'] for k in required if k in merged}),
            missing_clock_sources=sorted(missing))
        if sources_incomplete:
            evidence['clock_sources_incomplete'] = True
    return {'conflicted': conflicted, 'evidence': evidence,
            'current_sources': sorted(value['source'] for value in current.values()),
            'has_current_clock': bool(current), 'missing_sources': sorted(missing)}
