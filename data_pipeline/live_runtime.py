"""Attempt context, bounded candidate memory and session-scoped operator requests."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import uuid
from urllib.parse import urlsplit

from .live_telemetry import emit_live_event


def runtime_root() -> Path:
    return Path(__file__).resolve().parent / '.runtime'


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def context(call: dict) -> dict:
    return {'call_id': call.get('id'), 'ticker': call.get('ticker'),
            'schedule_revision': int(call.get('schedule_revision') or 0),
            'attempt_id': call.get('_live_attempt_id'),
            'capture_session_id': call.get('_capture_session_id')}


def prepare_attempt(call: dict) -> dict[str, str]:
    call.setdefault('_live_attempt_id', uuid.uuid4().hex)
    attempt = str(call['_live_attempt_id'])
    if not attempt.isalnum() or len(attempt) > 64:
        raise ValueError('Invalid live attempt ID')
    directory = runtime_root() / 'live-runs' / str(int(call.get('id') or 0)) / attempt
    call['_live_progress_dir'] = str(directory)
    if not (directory / 'attempt.json').exists():
        try:
            atomic_json(directory / 'attempt.json', {
                **context(call), 'created_at': datetime.now(timezone.utc).isoformat(),
                'event_date': str(call.get('webcast_date') or call.get('earning_at') or '')[:10],
            })
        except OSError as exc:
            # Evidence I/O must never prevent an otherwise valid live capture.
            print(f"[LiveRuntime] attempt evidence unavailable: {type(exc).__name__}", file=sys.stderr, flush=True)
    child_directory = str(directory)
    if os.getenv('WEBCAST_CAPTURE_RUNNER', 'docker').lower() != 'container':
        child_directory = '/app/' + str(directory.relative_to(Path(__file__).resolve().parents[1]))
    return {'WEBCAST_PROGRESS_DIR': child_directory,
            'WEBCAST_ATTEMPT_ID': attempt,
            'WEBCAST_CALL_DB_ID': str(call.get('id') or ''),
            'WEBCAST_SCHEDULE_REVISION': str(call.get('schedule_revision') or 0),
            'STT_CAPTURE_SESSION_ID': str(call.get('_capture_session_id') or ''),
            'TICKER': str(call.get('ticker') or '')}


def record(call: dict, stage: str, event: str, *, status=None, progress=False, **payload):
    directory = call.get('_live_progress_dir')
    if directory:
        return emit_live_event(stage, event, status=status, progress=progress,
                               directory=directory, context=context(call), **payload)


def memory_path(call: dict) -> Path:
    identity = '|'.join(str(call.get(k) or '') for k in
                        ('id', 'ticker', 'schedule_revision', 'schedule_discovery_fingerprint', 'webcast_date', 'earning_at'))
    return runtime_root() / 'live-candidates' / (hashlib.sha256(identity.encode()).hexdigest() + '.json')


def _unexpired_entries(data: dict, now: float) -> dict:
    entries = data.get('entries')
    if not isinstance(entries, dict):
        return {}
    valid = {}
    for key, entry in list(entries.items())[:256]:
        if not isinstance(entry, dict) or not isinstance(entry.get('url'), str):
            continue
        expiry = entry.get('expires_at')
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= now:
            continue
        valid[key] = entry
    return valid


def remember(call: dict, url: str, outcome: str, *, ttl_seconds=180, **details) -> None:
    if not url or not call.get("_live_attempt_id"):
        return
    try:
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            return
        path = memory_path(call)
        now = time.time()
        entries = _unexpired_entries(read_json(path), now)
        key = hashlib.sha256(url.encode()).hexdigest()
        previous = entries.get(key, {})
        try:
            count = max(0, int(previous.get('count') or 0)) + 1
        except (TypeError, ValueError, OverflowError):
            count = 1
        entries[key] = {**details, 'url': url, 'outcome': outcome, 'updated_at': now,
                        'expires_at': now + min(86400, ttl), 'count': count}
        def updated(item):
            value = item[1].get('updated_at')
            return value if isinstance(value, (int, float)) and math.isfinite(value) else 0
        entries = dict(sorted(entries.items(), key=updated)[-128:])
        atomic_json(path, {'revision': call.get('schedule_revision'), 'entries': entries})
    except (OSError, TypeError, ValueError, OverflowError) as exc:
        print(f"[LiveRuntime] candidate memory unavailable: {type(exc).__name__}", file=sys.stderr, flush=True)


def remembered(call: dict, outcomes: set[str]) -> dict[str, dict]:
    if not call.get("_live_attempt_id"):
        return {}
    try:
        return {entry['url']: entry for entry in _unexpired_entries(read_json(memory_path(call)), time.time()).values()
                if isinstance(entry.get('outcome'), str) and entry['outcome'] in outcomes and entry['url']}
    except (OSError, TypeError, ValueError, OverflowError):
        return {}


def remember_verified_route(call: dict, proof: dict) -> None:
    """Store authenticated route evidence separately from route failure notes.

    The caller validates proof first; loading never by itself authorizes it.
    Revision/fingerprint/event-day changes select a different evidence file.
    """
    if not call.get('_live_attempt_id'):
        return
    try:
        atomic_json(memory_path(call).with_suffix('.route.json'), {
            'context': {**context(call), 'event_date': str(call.get('webcast_date') or call.get('earning_at') or '')[:10]},
            'proof': proof,
        })
    except (OSError, TypeError, ValueError):
        record(call, 'discovery', 'verified_route_memory_unavailable', status='warning')


def remembered_verified_route(call: dict) -> dict | None:
    data = read_json(memory_path(call).with_suffix('.route.json'))
    expected = {**context(call), 'event_date': str(call.get('webcast_date') or call.get('earning_at') or '')[:10]}
    bound = data.get('context') or {}
    if (not isinstance(bound, dict) or any(str(bound.get(key)) != str(expected[key])
            for key in ('call_id', 'ticker', 'schedule_revision', 'event_date'))):
        return None
    proof = data.get('proof')
    return dict(proof) if isinstance(proof, dict) else None


def operator_route(call: dict) -> str | None:
    """An identity-bound hint only; never turn caller-supplied flags into proof."""
    try:
        call_id, revision = int(call.get('id') or 0), int(call.get('schedule_revision') or 0)
        data = read_json(runtime_root() / 'live-control' / f"route-{call_id}.json")
        expiry = data.get('expires_at')
        remaining = expiry - time.time() if isinstance(expiry, (int, float)) and not isinstance(expiry, bool) else -1
        if (int(data.get('call_id', -1)) != call_id or int(data.get('schedule_revision', -1)) != revision
                or not math.isfinite(remaining) or not 0 < remaining <= 12 * 3600 + 60):
            return None
        value = str(data.get('event_url') or '')
        issuer, target = urlsplit(str(call.get('ir_url') or '')), urlsplit(value)
        if (target.scheme not in {'http', 'https'} or target.username or target.password
                or not issuer.hostname or target.hostname != issuer.hostname):
            return None
        # Accessing port also rejects malformed/non-numeric URL authorities.
        if target.port not in {None, 80, 443}:
            return None
        return value
    except (OSError, TypeError, ValueError, OverflowError):
        return None


def consume_request(call: dict, name: str) -> dict | None:
    directory = call.get('_live_progress_dir')
    if not directory or name not in {'retry', 'stt-restart'}:
        return None
    path = Path(directory) / f'{name}.json'
    claimed = path.with_name(f'.{name}.claim-{uuid.uuid4().hex}.json')
    try:
        # Only one consumer can take this exact request. A later operator write
        # creates a new path and is never unlinked by this consumer.
        os.replace(path, claimed)
    except OSError:
        return None
    try:
        data = read_json(claimed)
        if not data:
            return None
        requested = datetime.fromisoformat(str(data['requested_at']).replace('Z', '+00:00'))
        if requested.tzinfo is None:
            raise ValueError('Request timestamp must include a timezone')
        age = time.time() - requested.timestamp()
        expected = context(call)
        valid = (math.isfinite(age) and 0 <= age <= 120
                 and all(expected.get(k) not in {None, ''} for k in ('call_id', 'attempt_id', 'capture_session_id'))
                 and all(str(data.get(k)) == str(v) for k, v in expected.items() if k != 'ticker'))
        if not valid:
            record(call, 'control', 'request_rejected', status='stale_or_wrong_session', request_id=data.get('request_id'))
            return None
        record(call, 'control', 'request_accepted', status=name, request_id=data.get('request_id'))
        return data
    except (OSError, KeyError, ValueError, TypeError, OverflowError):
        return None
    finally:
        try:
            claimed.unlink(missing_ok=True)
        except OSError:
            pass
