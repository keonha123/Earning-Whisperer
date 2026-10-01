"""Read current progress or request an identity-checked live recovery action."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import time
import uuid
from urllib.parse import urlsplit

from sqlalchemy import text
from ... import live_runtime
from ...live_telemetry import read_progress_snapshot
from ...storage.connection import engine
from ...operations import record_event


def fetch_call(call_id: int):
    with engine.connect() as connection:
        row = connection.execute(text('''SELECT c.id,c.ticker,c.status,c.schedule_revision,
          c.earning_at,c.webcast_date,c.scheduled_at_utc,c.stream_probe_status,
          c.stream_probe_retry_not_before,c.stream_probe_retry_reason,c.last_stream_probe_error,
          c.capture_session_id,c.capture_retry_not_before,c.capture_last_error,
          c.capture_lease_owner,c.stream_probe_lease_owner,s.ir_url
          FROM calls c JOIN stocks s ON s.ticker=c.ticker WHERE c.id=:id'''), {'id':call_id}).mappings().first()
    if row is None:
        raise ValueError('Call not found')
    return dict(row)


def current_attempt(call: dict):
    root = live_runtime.runtime_root() / 'live-runs' / str(call['id'])
    paths = sorted(root.glob('*/attempt.json'), key=lambda path: path.stat().st_mtime, reverse=True)[:100]
    for path in paths:
        meta = live_runtime.read_json(path)
        if (str(meta.get('schedule_revision')) == str(call['schedule_revision'])
                and (not call.get('capture_session_id') or
                     str(meta.get('capture_session_id')) == str(call['capture_session_id']))):
            return path.parent, meta
    # A pending row may still name an older completed capture; show the latest
    # attempt only for observation, never use it to control a running session.
    if call['status'] != 'running' and paths:
        return paths[0].parent, live_runtime.read_json(paths[0])
    return None, {}


def request_identity(call: dict, revision: int, expected_session: str | None):
    if int(call['schedule_revision']) != revision:
        raise ValueError('Schedule revision changed; refresh status before requesting recovery')
    if call['status'] == 'running' and (not expected_session or expected_session != call.get('capture_session_id')):
        raise ValueError('Running capture requires its exact --expected-session')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status','route','retry','restart-stt'])
    parser.add_argument('--call-id', type=int, required=True)
    parser.add_argument('--expected-revision', type=int)
    parser.add_argument('--expected-session')
    parser.add_argument('--event-url')
    parser.add_argument('--reason', default='operator recovery')
    args = parser.parse_args(argv)
    call = fetch_call(args.call_id)
    directory, meta = current_attempt(call)
    if args.action == 'status':
        with engine.connect() as connection:
            transcript = dict(connection.execute(text('''SELECT COUNT(*) AS stored_rows,
               MAX(sequence_no) AS last_sequence,MAX(created_at) AS last_saved_at
               FROM transcript_segments WHERE call_id=:session'''),
               {'session':call.get('capture_session_id') or ''}).mappings().one())
        from ...collectors.streams.browser.source_observation import summarize_live_verification
        progress = read_progress_snapshot(directory) if directory else {}
        print(json.dumps({'call':call,'attempt':meta,'progress_directory':str(directory) if directory else None,
                          'progress':progress,
                          'live_verification':summarize_live_verification(call, progress, transcript),
                          'transcript':transcript},default=str,ensure_ascii=False,indent=2))
        return 0
    if args.expected_revision is None:
        parser.error('Recovery commands require --expected-revision from a fresh status check')
    request_identity(call, args.expected_revision, args.expected_session)
    if args.action == 'route':
        issuer, target = urlsplit(call['ir_url'] or ''), urlsplit(args.event_url or '')
        if (target.scheme not in {'https','http'} or not issuer.hostname or target.hostname != issuer.hostname
                or target.username or target.password):
            parser.error('--event-url must be an official page on this call\'s exact issuer host')
        payload = {'call_id':call['id'],'schedule_revision':call['schedule_revision'],
                   'event_url':args.event_url,'expires_at':time.time()+12*3600,
                   'source':'operator_unverified_hint','target_identity_verified':False}
        live_runtime.atomic_json(live_runtime.runtime_root()/'live-control'/f"route-{call['id']}.json", payload)
        result = 'unverified official route queued for normal discovery validation; retry time unchanged'
    elif call['status'] == 'running':
        if directory is None or str(meta.get('capture_session_id')) != str(args.expected_session):
            raise ValueError('No current attempt matches the active capture session')
        payload = {**meta,'request_id':uuid.uuid4().hex,'requested_at':datetime.now(timezone.utc).isoformat(),
                   'reason':args.reason[:200]}
        action = 'stt-restart' if args.action == 'restart-stt' else 'retry'
        live_runtime.atomic_json(directory/f'{action}.json',payload)
        result = 'request queued; check progress for acceptance and completion'
    elif args.action == 'restart-stt':
        raise ValueError('No active capture to restart STT')
    else:
        if call['stream_probe_status'] == 'probing':
            raise ValueError('Discovery is active; preserve evidence and wait for its bounded result')
        if call['status'] not in {'upcoming','live','failed'}:
            raise ValueError('Completed or cancelled calls cannot be retried by this command')
        retry = call.get('stream_probe_retry_not_before')
        if call.get('stream_probe_retry_reason') == 'scheduled_start_wait' and retry and retry > datetime.now(timezone.utc).replace(tzinfo=None):
            raise ValueError('Verified pre-start waiting is preserved; do not override it as a failure')
        with engine.begin() as connection:
            updated = connection.execute(text('''UPDATE calls SET status='upcoming',
              stream_probe_status='pending',stream_probe_retry_not_before=NULL,stream_probe_retry_reason=NULL,
              capture_retry_not_before=NULL,last_stream_probe_at=NULL
              WHERE id=:id AND schedule_revision=:revision AND status IN ('upcoming','live','failed')
              AND stream_probe_status<>'probing' AND capture_lease_owner IS NULL
              AND stream_probe_lease_owner IS NULL AND schedule_superseded_by IS NULL
              AND NOT (COALESCE(stream_probe_retry_reason,'')='scheduled_start_wait'
                       AND COALESCE(stream_probe_retry_not_before,'1970-01-01')>UTC_TIMESTAMP())
              AND schedule_revalidation_status IN ('clear','provisional_watch')'''),
              {'id':call['id'],'revision':args.expected_revision}).rowcount
        if updated != 1:
            raise ValueError('Call changed or remains owned; recovery was not applied')
        result = 'eligible for the next ordinary watch cycle; schedule guards remain in effect'
    record_event('operator_recovery_requested',ticker=call['ticker'],call_id=call['id'],status=args.action,
                 schedule_revision=call['schedule_revision'],capture_session_id=call.get('capture_session_id'),
                 reason=args.reason[:200])
    print(json.dumps({'result':result,'call_id':call['id']},ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc))
