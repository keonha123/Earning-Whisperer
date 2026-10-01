"""Pure attempt accounting and actionable live-progress alert decisions."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone


def utc(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def outcome(row):
    code = row.get('error_code')
    if code == 'NOT_LIVE_YET' or row.get('error_category') == 'not_live_yet':
        return 'waiting'
    if code == 'CAPACITY_WAIT' or row.get('status') == 'capacity_wait':
        return 'deferred'
    if row.get('error') or code not in {None, '', 'NONE'}:
        return 'failed'
    if row.get('status') == 'stream_ready':
        return 'audio_ready'
    if row.get('status') in {'deferred', 'schedule_updated'}:
        return 'deferred'
    # Historical skipped-only events omitted the actual route outcome. Do not
    # invent a form failure or count the absence of evidence as successful work.
    return 'unknown'


def probe_outcomes(events):
    """One result per attempt; legacy starts bind subsequent unkeyed events.

    Explicit probe_result outranks compatibility discovery/skipped records.
    Unknown historical outcomes stay visible instead of becoming '0 failures'.
    """
    pending, selected = {}, {}
    for index, event in enumerate(events):
        kind = event.get('event_type')
        call = str(event.get('call_id') or event.get('ticker') or '')
        if not call:
            continue
        attempt = event.get('attempt_id') or event.get('probe_attempt_id')
        if kind == 'probe_started':
            pending[call] = (f'{call}:{attempt}' if attempt else f'{call}:legacy:{index}', event)
            continue
        if kind not in {'probe_result', 'capture_skipped', 'capture_deferred', 'discovery_result'}:
            continue
        if kind == 'discovery_result' and event.get('status') not in {'pending', 'error', 'failed'}:
            continue
        key, start = pending.get(call, (f'{call}:unkeyed:{index}', {}))
        if attempt:
            key = f'{call}:{attempt}'
        row = {**{k: start[k] for k in ('scheduled_at_utc', 'schedule_revision', 'attempt_id') if k in start}, **event}
        priority = 2 if kind == 'probe_result' else 1
        if key in selected and selected[key][0] > priority:
            continue
        row['attempt_key'] = key
        row['outcome'] = outcome(row)
        selected[key] = (priority, row)
    return sorted((row for _, row in selected.values()), key=lambda row: str(row.get('timestamp') or ''))


def progress_issues(results, calls, *, now, repeat_threshold=3, repeat_window_seconds=900,
                    no_text_seconds=300, waiting_grace_seconds=900):
    """Only current calls/revisions and recent outcomes can trigger live alerts.

    A waiting room is an observation, not a failure. After a longer grace it
    needs schedule/provider review, never an automatic capture-failed verdict.
    """
    now = utc(now)
    issues = []
    for call in calls:
        if call.get('status') not in {'upcoming', 'live', 'running'}:
            continue
        call_id = str(call.get('id'))
        revision = str(call.get('schedule_revision'))
        recent = []
        for row in results:
            stamp = utc(row.get('timestamp'))
            if (str(row.get('call_id')) == call_id and str(row.get('schedule_revision')) == revision
                    and stamp and 0 <= (now-stamp).total_seconds() <= repeat_window_seconds):
                recent.append(row)
        # A later audio-ready or new outcome breaks a previous identical-error
        # streak; changes of revision are already excluded above.
        streak = []
        for row in reversed(recent):
            if row['outcome'] != 'failed':
                break
            signature = row.get('failure_signature') or row.get('error_code')
            if streak and signature != (streak[0].get('failure_signature') or streak[0].get('error_code')):
                break
            streak.append(row)
        context = {'call_id': call.get('id'), 'ticker': call.get('ticker'),
                   'schedule_revision': call.get('schedule_revision')}
        text_at = utc(call.get('last_text_at'))
        if len(streak) >= repeat_threshold and not (text_at and text_at >= utc(streak[0]['timestamp'])):
            last = streak[0]
            issues.append({'key': f'repeated_live_failure:{call_id}:{revision}', 'severity': 'warning',
                'count': len(streak), **context, 'error_code': last.get('error_code'),
                'failure_stage': last.get('failure_stage'), 'next_action': last.get('next_action'),
                'failure_signature': last.get('failure_signature')})
        expected = utc(call.get('scheduled_at_utc')) or (
            utc(call.get('capture_started_at')) if call.get('status') == 'running' else None)
        if expected is None or now < expected:
            continue
        # Completed/stale events do not create indefinite historical alarms.
        if call.get('status') != 'running' and (now-expected).total_seconds() > 3*3600:
            continue
        last_progress = max(value for value in (expected, text_at) if value is not None)
        age = (now-last_progress).total_seconds()
        if age < no_text_seconds:
            continue
        waiting = call.get('waiting_observed') is True or (
            bool(recent) and recent[-1]['outcome'] == 'waiting')
        if waiting and age < waiting_grace_seconds:
            continue
        issues.append({'key': f'live_text_progress:{call_id}:{revision}',
            'severity': 'warning' if waiting else 'critical', **context,
            'count': 1, 'seconds_without_text': int(age),
            'state': 'waiting_beyond_expected_start' if waiting else 'no_durable_text_progress',
            'next_action': 'recheck_official_start_and_waiting_room' if waiting else 'inspect_route_form_audio_stt_archive',
            'capture_failed': False, 'last_text_at': text_at.isoformat() if text_at else None,
            'expected_start': expected.isoformat()})
    return issues


def annotate_waiting_observation(call, *, now):
    """Read bounded, fresh, session-bound local evidence without touching a player."""
    from . import live_runtime
    from .live_telemetry import read_progress_snapshot
    call['waiting_observed'] = False
    try:
        base = live_runtime.runtime_root() / 'live-runs' / str(int(call['id']))
        directories = sorted((p for p in base.iterdir() if p.is_dir()),
                             key=lambda p: p.stat().st_mtime, reverse=True)[:4]
        for directory in directories:
            snapshots = read_progress_snapshot(directory)
            for name in ('capture_source', 'stt'):
                row = snapshots.get(name, {})
                stamp = utc(row.get('timestamp_utc'))
                if (not stamp or not 0 <= (utc(now)-stamp).total_seconds() <= 120
                        or str(row.get('call_id')) != str(call['id'])
                        or str(row.get('schedule_revision')) != str(call.get('schedule_revision'))
                        or not call.get('capture_session_id')
                        or row.get('capture_session_id') != call['capture_session_id']):
                    continue
                if row.get('source_phase') == 'waiting_for_start' or (
                        name == 'stt' and row.get('status') == 'waiting_for_speech'
                        and row.get('speech_seen') is not True):
                    call['waiting_observed'] = True
                    return call
    except (OSError, TypeError, ValueError):
        pass
    return call
