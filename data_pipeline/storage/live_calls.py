"""Probe/capture leases, retry and completion state."""

from sqlalchemy import text
import hashlib
import json
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from math import ceil, isfinite
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo
from . import connection, policies, redaction, schedules, schema


def _transcript_completion_thresholds() -> tuple[int, int]:
    """Return the minimum durable transcript proof required for completion."""
    return (
        policies._env_int("STT_COMPLETION_MIN_SEGMENTS", 2),
        policies._env_int("STT_COMPLETION_MIN_CHARACTERS", 80),
    )


def _capture_retry_window_sql(alias: str = '', *, now: datetime | None = None):
    """Identical atomic guard for queue selection, claim and promotion."""
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    cutoff = now - timedelta(minutes=policies._env_int('DATE_STREAM_NEAR_END_MINUTES', 180))
    zone = ZoneInfo(os.getenv('DATE_STREAM_WATCH_TIMEZONE', 'America/New_York'))
    p = alias + '.' if alias else ''
    clause = f'''AND (
        (COALESCE({p}capture_attempts, 0) = 0 AND COALESCE({p}capture_session_id, '') = '')
        OR {p}scheduled_at_utc >= :capture_retry_cutoff
        OR ({p}scheduled_at_utc IS NULL AND
            COALESCE({p}webcast_date, DATE({p}earning_at)) >= :capture_retry_event_day)
    )'''
    return clause, {'capture_retry_cutoff': cutoff.replace(tzinfo=None),
                    'capture_retry_event_day': cutoff.astimezone(zone).date()}


def get_date_based_stream_candidates(
    days_ahead: int = 1,
    limit: int = 20,
    cooldown_minutes: int = 15,
    near_start_minutes: int = 20,
    near_end_minutes: int = 180,
    near_cooldown_minutes: int = 1,
    *,
    tickers: Iterable[str] | None = None,
    reference_time_utc: datetime | None = None,
) -> List[Dict[str, Any]]:
    """Return due calls; exact UTC windows survive local midnight boundaries."""
    selected_tickers = None if tickers is None else sorted({
        str(ticker).strip().upper().replace(".", "-") for ticker in tickers if str(ticker).strip()
    })
    if selected_tickers == []:
        return []
    schema.ensure_schedule_time_schema()
    now = reference_time_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    event_timezone = ZoneInfo(os.getenv("DATE_STREAM_WATCH_TIMEZONE", "America/New_York"))
    start_date = now.astimezone(event_timezone).date()
    end_date = start_date + timedelta(days=max(1, days_ahead))
    uncertain_grace = policies._nonnegative_env_int("DATE_STREAM_UNCERTAIN_DATE_GRACE_DAYS", 2)
    now_utc = now.replace(tzinfo=None)
    params: Dict[str, Any] = {
        "start_date": start_date, "end_date": end_date,
        "uncertain_start_date": start_date - timedelta(days=uncertain_grace),
        "uncertain_end_date": end_date + timedelta(days=uncertain_grace),
        "now_utc": now_utc,
        "window_start": now_utc - timedelta(minutes=max(0, int(near_end_minutes))),
        "window_end": now_utc + timedelta(minutes=max(0, int(near_start_minutes))),
        "cooldown_before": now_utc - timedelta(minutes=max(1, int(cooldown_minutes))),
        "near_cooldown_before": now_utc - timedelta(minutes=max(1, int(near_cooldown_minutes))),
        "overdue_before": now_utc - timedelta(minutes=policies._env_int(
            "DATE_STREAM_WATCH_MAX_GAP_MINUTES", 10,
        )),
        "candidate_limit": max(1, int(limit)),
        "time_fresh_after": now_utc - timedelta(minutes=policies._env_int(
            "SCHEDULE_TIME_LIVE_MAX_AGE_MINUTES", 120,
        )),
    }
    ticker_filter = ""
    retry_window_filter, retry_window_params = _capture_retry_window_sql('c', now=now)
    params.update(retry_window_params)
    if selected_tickers is not None:
        ticker_params = {f"watch_ticker_{index}": ticker for index, ticker in enumerate(selected_tickers)}
        params.update(ticker_params)
        ticker_filter = "AND c.ticker IN (" + ", ".join(f":{key}" for key in ticker_params) + ")"
    fresh_time = """(c.scheduled_at_utc IS NOT NULL
        AND COALESCE(c.time_verification_status, '') = 'verified'
        AND c.time_verified_at IS NOT NULL
        AND c.time_verified_at >= :time_fresh_after)"""
    overdue = """(
        (c.scheduled_at_utc IS NOT NULL
         OR COALESCE(c.webcast_date, DATE(c.earning_at)) <= :start_date)
        AND (c.last_stream_probe_at IS NULL OR c.last_stream_probe_at <= :overdue_before)
    )"""
    query = text(f"""
        SELECT c.id, c.ticker, c.earning_at, c.webcast_date, c.scheduled_at_utc,
               c.call_year, c.quarter, c.status,
               c.schedule_revision, c.schedule_observed_at,
               c.verified_fiscal_year, c.verified_fiscal_quarter,
               c.official_event_key, c.official_event_identity,
               CASE WHEN c.scheduled_at_utc IS NOT NULL AND NOT {fresh_time}
                    THEN 1 ELSE 0 END AS schedule_time_stale,
               c.video_url, c.stream_probe_attempts, c.capture_attempts,
               c.capture_session_id,
               c.capture_retry_not_before, c.stream_probe_retry_not_before,
               c.stream_probe_retry_reason, c.time_verification_status,
               c.schedule_revalidation_status, c.schedule_revalidation_reason,
               c.schedule_revalidation_evidence,
               c.schedule_source, c.schedule_evidence,
               c.schedule_discovery_fingerprint, c.schedule_discovery_checked_at, c.time_verified_at,
               s.company_name, s.ir_url,
               c.event_url, c.webcast_url
        FROM calls c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE c.status IN ('upcoming', 'live')
          AND c.schedule_superseded_by IS NULL
          AND c.schedule_revalidation_status IN ('clear', 'provisional_watch')
          {ticker_filter}
          {retry_window_filter}
          AND (
              (
                  c.scheduled_at_utc IS NOT NULL
                  AND c.scheduled_at_utc >= :window_start
                  AND c.scheduled_at_utc <= :window_end
              )
              OR (
                  (c.scheduled_at_utc IS NULL OR NOT {fresh_time})
                  AND (
                      (c.schedule_revalidation_status = 'clear'
                       AND COALESCE(c.webcast_date, DATE(c.earning_at)) >= :start_date
                       AND COALESCE(c.webcast_date, DATE(c.earning_at)) < :end_date)
                      OR
                      ((c.schedule_revalidation_status = 'provisional_watch'
                         OR (c.scheduled_at_utc IS NOT NULL AND NOT {fresh_time}))
                       AND COALESCE(c.webcast_date, DATE(c.earning_at)) >= :uncertain_start_date
                       AND COALESCE(c.webcast_date, DATE(c.earning_at)) < :uncertain_end_date)
                  )
              )
              OR (
                  c.scheduled_at_utc IS NULL
                  AND (COALESCE(c.capture_attempts, 0) > 0 OR COALESCE(c.capture_session_id, '') <> '')
                  AND COALESCE(c.webcast_date, DATE(c.earning_at)) >= :capture_retry_event_day
                  AND COALESCE(c.webcast_date, DATE(c.earning_at)) <= :start_date
              )
          )
          AND (c.capture_retry_not_before IS NULL OR c.capture_retry_not_before <= :now_utc)
          AND (c.stream_probe_retry_not_before IS NULL OR c.stream_probe_retry_not_before <= :now_utc
               OR (c.stream_probe_retry_reason = 'scheduled_start_wait' AND NOT {fresh_time}))
          AND (
              c.last_stream_probe_at IS NULL
              OR c.last_stream_probe_at <= :cooldown_before
              OR (c.capture_retry_not_before IS NOT NULL AND c.capture_retry_not_before <= :now_utc)
              OR (c.scheduled_at_utc IS NOT NULL AND c.last_stream_probe_at <= :near_cooldown_before)
          )
        ORDER BY
            CASE WHEN {overdue} THEN 0 ELSE 1 END,
            CASE WHEN {overdue} THEN COALESCE(c.last_stream_probe_at, '1970-01-01 00:00:00') END ASC,
            CASE
                WHEN c.scheduled_at_utc IS NOT NULL THEN 0
                WHEN COALESCE(c.webcast_date, DATE(c.earning_at)) = :start_date
                     AND c.schedule_revalidation_status = 'clear' THEN 1
                WHEN c.capture_retry_not_before IS NOT NULL AND c.capture_retry_not_before <= :now_utc THEN 2
                WHEN COALESCE(c.webcast_date, DATE(c.earning_at)) = :start_date THEN 3
                ELSE 4
            END,
            CASE WHEN c.last_stream_probe_at IS NULL THEN 0 ELSE 1 END,
            c.last_stream_probe_at ASC,
            COALESCE(c.webcast_date, DATE(c.earning_at)) ASC,
            c.ticker ASC
        LIMIT :candidate_limit
    """)
    with connection.engine.connect() as conn:
        result = conn.execute(query, params)
        return [dict(row._mapping) for row in result]


def claim_stream_probe(
    call_id: int,
    cooldown_minutes: int = 15,
    *,
    expected_event_date: object | None = None,
    expected_discovery_fingerprint: str | None = None,
    expected_schedule_revision: int | None = None,
) -> bool:
    """Atomically claim one date-based probe with a recoverable DB lease."""
    schema.ensure_schedule_time_schema()
    lease_minutes = policies._env_int("DATE_STREAM_PROBE_LEASE_MINUTES", 10)
    cooldown_value = max(1, int(cooldown_minutes))
    owner = _pipeline_worker_id()
    expected_date = policies._coerce_schedule_date(expected_event_date)
    identity_filter = ""
    params: Dict[str, Any] = {"call_id": call_id, "owner": owner,
        "time_fresh_after": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            minutes=policies._env_int("SCHEDULE_TIME_LIVE_MAX_AGE_MINUTES", 120))}
    if expected_date is not None:
        identity_filter = """
          AND COALESCE(webcast_date, DATE(earning_at)) = :expected_event_date
          AND schedule_discovery_fingerprint <=> :expected_discovery_fingerprint
        """
        params.update(
            {
                "expected_event_date": expected_date,
                "expected_discovery_fingerprint": (
                    str(expected_discovery_fingerprint)[:64]
                    if expected_discovery_fingerprint
                    else None
                ),
            }
        )
    if expected_schedule_revision is not None:
        identity_filter += " AND schedule_revision = :expected_schedule_revision"
        params["expected_schedule_revision"] = int(expected_schedule_revision)
    retry_filter, retry_params = _capture_retry_window_sql()
    identity_filter += '\n' + retry_filter
    params.update(retry_params)
    query = text(
        """
        UPDATE calls
        SET stream_probe_status = 'probing',
            stream_probe_attempts = stream_probe_attempts + 1,
            last_stream_probe_at = UTC_TIMESTAMP(),
            last_stream_probe_error = NULL,
            stream_probe_retry_not_before = NULL,
            stream_probe_retry_reason = NULL,
            capture_retry_not_before = NULL,
            stream_probe_lease_owner = :owner,
            stream_probe_lease_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL {lease_minutes} MINUTE),
            stream_probe_heartbeat_at = UTC_TIMESTAMP()
        WHERE id = :call_id
          AND status IN ('upcoming', 'live')
          AND schedule_superseded_by IS NULL
          AND schedule_revalidation_status IN ('clear', 'provisional_watch')
          {identity_filter}
          AND (
              stream_probe_status <> 'probing'
              OR stream_probe_lease_until IS NULL
              OR stream_probe_lease_until <= UTC_TIMESTAMP()
          )
          AND (
              last_stream_probe_at IS NULL
              OR last_stream_probe_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL {cooldown_value} MINUTE)
              OR capture_retry_not_before <= UTC_TIMESTAMP()
          )
          AND (
              stream_probe_retry_not_before IS NULL
              OR stream_probe_retry_not_before <= UTC_TIMESTAMP()
              OR (stream_probe_retry_reason = 'scheduled_start_wait' AND
                  (scheduled_at_utc IS NULL OR COALESCE(time_verification_status, '') <> 'verified'
                   OR time_verified_at IS NULL OR time_verified_at < :time_fresh_after))
          )
        """.format(
            lease_minutes=lease_minutes,
            cooldown_value=cooldown_value,
            identity_filter=identity_filter,
        )
    )
    with connection.engine.begin() as conn:
        result = conn.execute(query, params)
        return result.rowcount == 1


def record_stream_probe(
    call_id: int,
    stream_ready: bool,
    error: str | None = None,
    *,
    watch_state: str | None = None,
    expected_date: object | None = None,
    schedule_observation: Dict[str, Any] | None = None,
    expected_schedule_revision: int | None = None,
) -> Dict[str, Any]:
    """Finish a probe, optionally committing its validated clock atomically.

    Browser callers provide structured evidence only after target validation.
    Old callers retain their retry policy API; guarded callers also receive the
    committed schedule and whether their held browser may be promoted.
    """
    policy = policies.stream_probe_retry_policy(
        error,
        watch_state=watch_state,
        expected_date=expected_date,
    ) if not stream_ready else {
        "reason": None,
        "retry_delay_minutes": 0,
        "requires_schedule_refresh": False,
    }
    if schedule_observation is not None or expected_schedule_revision is not None:
        return _record_probe_schedule_observation(
            call_id, stream_ready, error, policy, expected_date=expected_date,
            expected_revision=expected_schedule_revision,
            observation=schedule_observation,
        )
    with connection.engine.begin() as conn:
        _write_stream_probe_result(conn, call_id, stream_ready, error, policy)
    return policy


def _write_stream_probe_result(conn, call_id, stream_ready, error, policy):
    retry_minutes = max(1, int(policy["retry_delay_minutes"] or 1))
    owner = _pipeline_worker_id()
    query = text(
        f"""
        UPDATE calls
        SET stream_probe_status = :stream_probe_status,
            stream_detected_at = CASE WHEN :stream_ready THEN UTC_TIMESTAMP() ELSE stream_detected_at END,
            last_stream_probe_error = :error,
            stream_probe_retry_not_before = CASE
                WHEN :stream_ready THEN NULL
                WHEN :retry_delay_minutes > 0 THEN DATE_ADD(
                    UTC_TIMESTAMP(), INTERVAL {retry_minutes} MINUTE
                )
                ELSE NULL
            END,
            stream_probe_retry_reason = CASE
                WHEN :stream_ready THEN NULL
                ELSE :retry_reason
            END,
            stream_probe_lease_owner = NULL,
            stream_probe_lease_until = NULL,
            stream_probe_heartbeat_at = NULL
        WHERE id = :call_id
          AND (
              stream_probe_lease_owner = :owner
          )
    """)
    return conn.execute(
        query,
        {
            "call_id": call_id,
            "owner": owner,
            "stream_ready": stream_ready,
            "stream_probe_status": "stream_ready" if stream_ready else "pending",
            "error": redaction.redact_sensitive_text(error[:1000]) if error else None,
            "retry_delay_minutes": int(policy["retry_delay_minutes"] or 0),
            "retry_reason": policy["reason"],
        },
    ).rowcount == 1


def _browser_source_timezone(label: str):
    """Resolve exactly the IANA, fixed abbreviation, and ISO zones parser emits."""
    from ..collectors.schedules.call_times import _zone
    zone, _ = _zone(label)
    if zone is not None:
        return zone
    offset = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", label)
    if offset and int(offset[2]) <= 23 and int(offset[3]) <= 59:
        delta = timedelta(hours=int(offset[2]), minutes=int(offset[3]))
        return timezone(delta if offset[1] == "+" else -delta)
    raise ValueError("unrecognized browser clock timezone")


def _record_probe_schedule_observation(
    call_id, stream_ready, error, policy, *, expected_date, expected_revision, observation,
):
    """Release the owned probe and apply its clock under the same ticker lock.

    No other refresher can interleave a schedule write between ownership check,
    lease release, and official observation. Material changes deliberately
    invalidate the current browser handoff; the next probe uses the new revision.
    """
    result = {**policy, "accepted": False, "schedule_applied": False,
              "schedule_changed": False, "capture_handoff_valid": False,
              "schedule_context": None}
    schema.ensure_schedule_time_schema()
    owner = _pipeline_worker_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with connection.engine.begin() as conn:
        # Match official-refresh lock ordering to prevent ticker-level deadlocks.
        rows = [dict(row) for row in conn.execute(text("""
            SELECT * FROM calls
            WHERE ticker = (SELECT ticker FROM calls WHERE id = :call_id)
            ORDER BY id FOR UPDATE
        """), {"call_id": call_id}).mappings()]
        row = next((item for item in rows if int(item["id"]) == int(call_id)), None)
        result["schedule_context"] = row
        if (not row or row.get("status") not in {"upcoming", "live"}
                or row.get("schedule_superseded_by")
                or row.get("stream_probe_status") != "probing"
                or row.get("stream_probe_lease_owner") != owner
                or expected_revision is None
                or int(row.get("schedule_revision") or 0) != int(expected_revision)):
            return result
        lease = row.get("stream_probe_lease_until")
        if not lease or schedules._utc_naive(lease) <= now:
            return result
        wanted_day = policies._coerce_schedule_date(expected_date)
        stored_day = policies._coerce_schedule_date(row.get("webcast_date") or row.get("earning_at"))
        if wanted_day is None or stored_day != wanted_day:
            return result

        # Only the browser's matched event day is accepted here. Official issuer
        # reconciliation separately handles confirmed changes to another day.
        evidence = dict(observation or {})
        valid = policies._coerce_schedule_date(evidence.get("webcast_date")) == stored_day
        try:
            if not all(isinstance(evidence.get(field), (str, datetime))
                       for field in ("scheduled_at_utc", "observed_at")):
                raise ValueError("missing clock evidence")
            observed = schedules._utc_naive(evidence["observed_at"])
            start = schedules._utc_naive(evidence["scheduled_at_utc"])
            zone = _browser_source_timezone(str(evidence.get("source_timezone") or ""))
            valid = valid and start.replace(tzinfo=timezone.utc).astimezone(zone).date() == stored_day
            valid = valid and observed <= now + timedelta(minutes=1)
            # Older completions from the same worker cannot overwrite a newer
            # probe (or a newer page observation at the same schedule revision).
            for field in ("last_stream_probe_at", "schedule_observed_at"):
                if row.get(field) and observed < schedules._utc_naive(row[field]):
                    return result
        except (ValueError, TypeError, KeyError):
            valid = False

        _write_stream_probe_result(conn, call_id, stream_ready, error, policy)
        result["accepted"] = True
        revision = None
        if valid:
            evidence.update(expected_revision=int(expected_revision), observed_at=observed,
                            scheduled_at_utc=start, webcast_date=stored_day)
            revision = schedules.update_verified_schedule_time(
                call_id, evidence, _connection=conn,
            )
        current = dict(conn.execute(text("SELECT * FROM calls WHERE id = :call_id"),
                                    {"call_id": call_id}).mappings().one())
        result["schedule_applied"] = revision is not None
        clock_conflicted = bool(valid and current.get('schedule_revalidation_status') == 'provisional_watch'
                                and current.get('schedule_revalidation_reason') == 'ambiguous_call_time')
        result['schedule_conflicted'] = clock_conflicted
        if clock_conflicted:
            from ..collectors.schedules.clock_reconciliation import read_clock_evidence
            clock_details = read_clock_evidence(current)
            result['missing_clock_sources'] = clock_details.get('missing_clock_sources', [])
            result['clock_observations'] = clock_details.get('clock_observations', [])
        changed = int(current.get("schedule_revision") or 0) != int(expected_revision)
        result["schedule_changed"] = changed
        result["capture_handoff_valid"] = bool(
            stream_ready and not changed
            and (observation is None or (valid and (revision is not None or clock_conflicted)))
        )

        # A verified DB clock owns scheduled waiting. Do not round to a retry
        # minute or allow an old NOT_LIVE_YET string to override a moved time.
        fresh_clock = bool(current.get("scheduled_at_utc")
            and current.get("time_verification_status") == "verified"
            and current.get("time_verified_at")
            and schedules._utc_naive(current["time_verified_at"]) >= now - timedelta(
                minutes=policies._env_int("SCHEDULE_TIME_LIVE_MAX_AGE_MINUTES", 120)))
        if fresh_clock:
            retry_at = schedules._utc_naive(current["scheduled_at_utc"]) - timedelta(
                minutes=policies._nonnegative_env_int("DATE_STREAM_EARLY_ENTRY_MINUTES", 5))
            if retry_at > now:
                conn.execute(text("""
                    UPDATE calls SET stream_probe_status = 'pending',
                        stream_probe_retry_not_before = :retry_at,
                        stream_probe_retry_reason = 'scheduled_start_wait'
                    WHERE id = :call_id
                """), {"call_id": call_id, "retry_at": retry_at})
                current.update(stream_probe_status="pending", stream_probe_retry_not_before=retry_at,
                               stream_probe_retry_reason="scheduled_start_wait")
                result.update(reason="scheduled_start_wait", requires_schedule_refresh=False,
                              retry_delay_minutes=max(1, ceil((retry_at - now).total_seconds() / 60)),
                              capture_handoff_valid=False)
            elif changed:
                result.update(reason=None, retry_delay_minutes=0, requires_schedule_refresh=False)
            elif policy["reason"] == "scheduled_start_wait":
                delay = policies._env_int("DATE_STREAM_NEAR_LIVE_RETRY_MINUTES", 1)
                retry_at = now + timedelta(minutes=delay)
                conn.execute(text("""
                    UPDATE calls SET stream_probe_retry_not_before = :retry_at,
                        stream_probe_retry_reason = 'transient_error'
                    WHERE id = :call_id
                """), {"call_id": call_id, "retry_at": retry_at})
                current.update(stream_probe_retry_not_before=retry_at,
                               stream_probe_retry_reason="transient_error")
                result.update(reason="transient_error", retry_delay_minutes=delay,
                              requires_schedule_refresh=False)
        elif policy["reason"] == "scheduled_start_wait":
            # A quoted future time cannot extend an expired DB clock's wait.
            # Structured, matched browser observations refresh it above first.
            delay = policies._env_int("DATE_STREAM_NEAR_LIVE_RETRY_MINUTES", 1)
            retry_at = now + timedelta(minutes=delay)
            conn.execute(text("""
                UPDATE calls SET stream_probe_retry_not_before = :retry_at,
                    stream_probe_retry_reason = 'transient_error' WHERE id = :call_id
            """), {"call_id": call_id, "retry_at": retry_at})
            current.update(stream_probe_retry_not_before=retry_at, stream_probe_retry_reason="transient_error")
            result.update(reason="transient_error", retry_delay_minutes=delay, requires_schedule_refresh=False)
        if clock_conflicted and not result['capture_handoff_valid']:
            result.update(reason='schedule_clock_conflict', requires_schedule_refresh=True)
        result["schedule_context"] = current
        return result


def heartbeat_stream_probe(call_id: int) -> bool:
    """Extend a probe lease while its browser subprocess is still running."""
    schema.ensure_schedule_time_schema()
    lease_minutes = max(1, int(os.getenv("DATE_STREAM_PROBE_LEASE_MINUTES", "10")))
    owner = _pipeline_worker_id()
    query = text(
        """
        UPDATE calls
        SET stream_probe_lease_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL {lease_minutes} MINUTE),
            stream_probe_heartbeat_at = UTC_TIMESTAMP()
        WHERE id = :call_id
          AND stream_probe_status = 'probing'
          AND stream_probe_lease_owner = :owner
        """.format(lease_minutes=lease_minutes)
    )
    with connection.engine.begin() as conn:
        return conn.execute(query, {"call_id": call_id, "owner": owner}).rowcount == 1


def mark_call_running(
    call_id: int,
    *,
    capture_session_id: str | None = None,
    expected_event_date: object | None = None,
    expected_discovery_fingerprint: str | None = None,
    expected_schedule_revision: int | None = None,
) -> bool:
    """Claim a capture lease while preserving the legacy call-site API."""
    schema.ensure_schedule_time_schema()
    lease_minutes = policies._env_int("DATE_STREAM_CAPTURE_LEASE_MINUTES", 120)
    owner = _pipeline_worker_id()
    expected_date = policies._coerce_schedule_date(expected_event_date)
    identity_filter = ""
    params: Dict[str, Any] = {
        "call_id": call_id,
        "owner": owner,
        "capture_session_id": str(capture_session_id or "")[:128] or None,
    }
    if expected_date is not None:
        identity_filter = """
          AND COALESCE(webcast_date, DATE(earning_at)) = :expected_event_date
          AND schedule_discovery_fingerprint <=> :expected_discovery_fingerprint
        """
        params.update(
            {
                "expected_event_date": expected_date,
                "expected_discovery_fingerprint": (
                    str(expected_discovery_fingerprint)[:64]
                    if expected_discovery_fingerprint
                    else None
                ),
            }
        )
    if expected_schedule_revision is not None:
        identity_filter += " AND schedule_revision = :expected_schedule_revision"
        params["expected_schedule_revision"] = int(expected_schedule_revision)
    retry_filter, retry_params = _capture_retry_window_sql()
    identity_filter += '\n' + retry_filter
    params.update(retry_params)
    query = text("""
        UPDATE calls
        SET capture_previous_status = status,
            status = 'running',
            capture_attempts = capture_attempts + 1,
            capture_retry_not_before = NULL,
            capture_last_error = NULL,
            capture_lease_owner = :owner,
            capture_lease_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL {lease_minutes} MINUTE),
            capture_started_at = COALESCE(capture_started_at, UTC_TIMESTAMP()),
            capture_heartbeat_at = UTC_TIMESTAMP(),
            capture_session_id = :capture_session_id
        WHERE id = :call_id
          AND status IN ('upcoming', 'live')
          AND schedule_superseded_by IS NULL
          AND schedule_revalidation_status IN ('clear', 'provisional_watch')
          {identity_filter}
          AND (
              capture_lease_until IS NULL
              OR capture_lease_until <= UTC_TIMESTAMP()
          )
        """.format(
            lease_minutes=lease_minutes,
            identity_filter=identity_filter,
        )
    )

    with connection.engine.begin() as conn:
        result = conn.execute(query, params)
        return result.rowcount == 1


def heartbeat_call_capture(
    call_id: int,
    *,
    capture_session_id: str | None = None,
) -> bool:
    """Extend the capture lease while its browser/STT process is alive."""
    schema.ensure_schedule_time_schema()
    lease_minutes = policies._env_int("DATE_STREAM_CAPTURE_LEASE_MINUTES", 120)
    owner = _pipeline_worker_id()
    session_filter = ""
    params: Dict[str, Any] = {"call_id": call_id, "owner": owner}
    if capture_session_id:
        session_filter = " AND capture_session_id = :capture_session_id"
        params["capture_session_id"] = str(capture_session_id)[:128]
    query = text(
        """
        UPDATE calls
        SET capture_lease_until = DATE_ADD(UTC_TIMESTAMP(), INTERVAL {lease_minutes} MINUTE),
            capture_heartbeat_at = UTC_TIMESTAMP()
        WHERE id = :call_id
          AND status = 'running'
          AND capture_lease_owner = :owner
          {session_filter}
        """.format(
            lease_minutes=lease_minutes,
            session_filter=session_filter,
        )
    )
    with connection.engine.begin() as conn:
        return conn.execute(query, params).rowcount == 1


def update_capture_manifest(call_id: int, manifest_path: str) -> None:
    """Persist the probe-to-capture handoff location for audits and recovery."""
    schema.ensure_schedule_time_schema()
    owner = _pipeline_worker_id()
    query = text("""
        UPDATE calls
        SET capture_manifest_path = :manifest_path,
            capture_heartbeat_at = UTC_TIMESTAMP()
        WHERE id = :call_id
          AND (
              capture_lease_owner = :owner
          )
    """)
    with connection.engine.begin() as conn:
        conn.execute(
            query,
            {
                "call_id": call_id,
                "owner": owner,
                "manifest_path": str(manifest_path)[:2048],
            },
        )


def complete_call_capture_from_transcript(
    call_id: int,
    transcript_call_id: str,
) -> Dict[str, Any]:
    """Complete a live call only with a positively observed event end.

    A timer, quiet input, or a clean process exit cannot prove that an earnings
    call finished. Apply this even to older workers' successful terminal rows.
    """
    schema.ensure_schedule_time_schema()
    schema.ensure_transcript_archive_schema()
    owner = _pipeline_worker_id()
    session_id = str(transcript_call_id or "")[:128]
    minimum_segments, minimum_characters = _transcript_completion_thresholds()
    if not session_id:
        return {
            "completed": False,
            "segment_count": 0,
            "text_character_count": 0,
            "minimum_segment_count": minimum_segments,
            "minimum_text_character_count": minimum_characters,
            "session_end_count": 0,
            "successful_end_count": 0,
            "identity_verified_end_count": 0,
            "valid_end_count": 0,
            "session_end_reason": None,
            "ownership_lost": False,
        }

    with connection.engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT id
                FROM calls
                WHERE id = :call_id
                  AND status = 'running'
                  AND capture_lease_owner = :owner
                  AND capture_session_id = :capture_session_id
                FOR UPDATE
            """),
            {
                "call_id": call_id,
                "owner": owner,
                "capture_session_id": session_id,
            },
        ).mappings().first()
        if not row:
            return {
                "completed": False,
                "segment_count": 0,
                "text_character_count": 0,
                "minimum_segment_count": minimum_segments,
                "minimum_text_character_count": minimum_characters,
                "session_end_count": 0,
                "successful_end_count": 0,
                "identity_verified_end_count": 0,
                "valid_end_count": 0,
                "session_end_reason": None,
                "ownership_lost": True,
            }

        summary = conn.execute(
            text("""
                SELECT COUNT(*) AS segment_count,
                       COALESCE(SUM(CHAR_LENGTH(TRIM(text_chunk))), 0)
                           AS text_character_count,
                       COALESCE(SUM(is_session_end = TRUE), 0) AS session_end_count,
                       COALESCE(SUM(
                           is_session_end = TRUE
                           AND session_success_eligible = TRUE
                       ), 0) AS successful_end_count,
                       COALESCE(SUM(
                           is_session_end = TRUE
                           AND target_identity_verified = TRUE
                       ), 0) AS identity_verified_end_count,
                       COALESCE(SUM(
                           is_session_end = TRUE
                           AND session_success_eligible = TRUE
                           AND target_identity_verified = TRUE
                           AND session_end_reason = 'event_ended'
                       ), 0) AS valid_end_count,
                       MAX(CASE
                           WHEN is_session_end = TRUE THEN session_end_reason
                       END) AS session_end_reason
                FROM transcript_segments
                WHERE call_id = :capture_session_id
            """),
            {"capture_session_id": session_id},
        ).mappings().one()
        segment_count = int(summary.get("segment_count") or 0)
        text_character_count = int(summary.get("text_character_count") or 0)
        session_end_count = int(summary.get("session_end_count") or 0)
        successful_end_count = int(summary.get("successful_end_count") or 0)
        identity_verified_end_count = int(
            summary.get("identity_verified_end_count") or 0
        )
        valid_end_count = int(summary.get("valid_end_count") or 0)
        completed = (
            segment_count >= minimum_segments
            and text_character_count >= minimum_characters
            and valid_end_count > 0
        )
        if completed:
            conn.execute(
                text("""
                    UPDATE calls
                    SET status = 'completed',
                        capture_lease_owner = NULL,
                        capture_lease_until = NULL,
                        capture_started_at = NULL,
                        capture_heartbeat_at = NULL,
                        capture_previous_status = NULL,
                        capture_retry_not_before = NULL,
                        capture_last_error = NULL
                    WHERE id = :call_id
                      AND capture_lease_owner = :owner
                      AND capture_session_id = :capture_session_id
                """),
                {
                    "call_id": call_id,
                    "owner": owner,
                    "capture_session_id": session_id,
                },
            )
        return {
            "completed": completed,
            "segment_count": segment_count,
            "text_character_count": text_character_count,
            "minimum_segment_count": minimum_segments,
            "minimum_text_character_count": minimum_characters,
            "session_end_count": session_end_count,
            "successful_end_count": successful_end_count,
            "identity_verified_end_count": identity_verified_end_count,
            "valid_end_count": valid_end_count,
            "session_end_reason": summary.get("session_end_reason"),
            "ownership_lost": False,
        }


def complete_recovered_call_captures_from_transcripts(
    transcript_call_ids: Iterable[str] | None = None,
    *,
    limit: int = 50,
) -> int:
    """Finish requeued captures once a locally spooled terminal transcript lands.

    The normal capture worker owns a lease while it calls
    :func:`complete_call_capture_from_transcript`. If MySQL is unavailable at
    that moment, the worker deliberately requeues the call. This recovery path
    accepts only the same durable proof (text plus a successful, identity-verified
    terminal marker) and only when the stored capture session still matches.
    """
    schema.ensure_schedule_time_schema()
    schema.ensure_transcript_archive_schema()
    session_ids = {
        str(session_id).strip()[:128]
        for session_id in (transcript_call_ids or ())
        if str(session_id).strip()
    }
    # A database outage can happen immediately after the final segment was
    # archived but before the capture worker releases its lease. Scan a bounded
    # set of requeued/failed sessions as well, so that narrow timing window is
    # recoverable even when the local spool has already been drained. A terminal
    # marker is emitted only as the STT process is stopping, so an in-flight
    # `running` row with that proof is also safe to reconcile.
    recovery_limit = max(1, int(limit))
    minimum_segments, minimum_characters = _transcript_completion_thresholds()
    with connection.engine.connect() as conn:
        pending_rows = conn.execute(
            text("""
                SELECT capture_session_id
                FROM calls
                WHERE capture_session_id IS NOT NULL
                  AND capture_session_id <> ''
                  AND status IN ('upcoming', 'live', 'running', 'failed')
                ORDER BY capture_started_at ASC, id ASC
                LIMIT :limit
            """),
            {"limit": recovery_limit},
        ).mappings().all()
    session_ids.update(
        str(row.get("capture_session_id") or "").strip()[:128]
        for row in pending_rows
        if str(row.get("capture_session_id") or "").strip()
    )
    completed_count = 0
    for session_id in session_ids:
        with connection.engine.begin() as conn:
            row = conn.execute(
                text("""
                    SELECT id
                    FROM calls
                    WHERE capture_session_id = :capture_session_id
                      AND status IN ('upcoming', 'live', 'running', 'failed')
                    FOR UPDATE
                """),
                {"capture_session_id": session_id},
            ).mappings().first()
            if not row:
                continue

            summary = conn.execute(
                text("""
                SELECT COUNT(*) AS segment_count,
                           COALESCE(SUM(CHAR_LENGTH(TRIM(text_chunk))), 0)
                               AS text_character_count,
                           COALESCE(SUM(is_session_end = TRUE), 0) AS session_end_count,
                           COALESCE(SUM(
                               is_session_end = TRUE
                               AND session_success_eligible = TRUE
                               AND target_identity_verified = TRUE
                               AND session_end_reason = 'event_ended'
                           ), 0) AS valid_end_count
                    FROM transcript_segments
                    WHERE call_id = :capture_session_id
                """),
                {"capture_session_id": session_id},
            ).mappings().one()
            if (
                int(summary.get("segment_count") or 0) < minimum_segments
                or int(summary.get("text_character_count") or 0) < minimum_characters
                or int(summary.get("valid_end_count") or 0) <= 0
            ):
                continue

            result = conn.execute(
                text("""
                    UPDATE calls
                    SET status = 'completed',
                        stream_probe_status = 'stream_ready',
                        capture_lease_owner = NULL,
                        capture_lease_until = NULL,
                        capture_started_at = NULL,
                        capture_heartbeat_at = NULL,
                        capture_previous_status = NULL,
                        capture_retry_not_before = NULL,
                        capture_last_error = NULL
                    WHERE id = :call_id
                      AND capture_session_id = :capture_session_id
                """),
                {
                    "call_id": row["id"],
                    "capture_session_id": session_id,
                },
            )
            completed_count += int(result.rowcount or 0)
    return completed_count


def _event_end_url(value: object) -> str:
    """Keep event-identifying paths and queries; discard only fragment noise."""
    parsed = urlsplit(str(value or '').strip())
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        return ''
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/'), parsed.query, ''))


def _load_retrospective_event_end(path_value: str, expected_sha256: str) -> dict[str, Any] | None:
    """Verify an immutable review artifact and every source file it cites."""
    try:
        path = Path(path_value)
        if not path.is_absolute() or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
            return None
        if not 0 < path.stat().st_size <= 65536:
            return None
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            return None
        proof = json.loads(raw)
        if not isinstance(proof, dict) or proof.get('version') != 1 or proof.get('reason') != 'event_ended':
            return None
        if proof.get('target_identity_verified') is not True or proof.get('coverage') not in {'partial', 'unverified'}:
            return None
        sources = proof.get('sources')
        if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
            return None
        for source in sources:
            source_path = Path(source['path'])
            if not source_path.is_absolute() or source_path == path:
                return None
            with source_path.open('rb') as handle:
                if hashlib.file_digest(handle, 'sha256').hexdigest() != source['sha256']:
                    return None
        evidence = str(proof.get('evidence') or '').strip()
        if not evidence or len(evidence) > 16000:
            return None
        kind = proof.get('evidence_kind')
        if kind == 'browser_event_status':
            if (int(proof.get('observations') or 0) < 2
                    or len({str(Path(item['path']).resolve()) for item in sources}) < 2
                    or not re.search(
                r'\b(?:(?:this|the)\s+)?(?:broadcast|webcast|webinar|event|conference\s+call|call)\s+'
                r'(?:has\s+)?(?:now\s+)?(?:ended|concluded|finished)\b', evidence, re.I,
            )):
                return None
        elif kind == 'operator_closing':
            from ..live_end import explicit_operator_close
            normalized = evidence.replace('’', "'")
            idle = float(proof.get('no_following_speech_seconds') or 0)
            if (not isfinite(idle) or idle < 60
                    or not explicit_operator_close(normalized)):
                return None
            if int(proof.get('terminal_sequence', -1)) < 0:
                return None
        else:
            return None
        return proof
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None


def record_verified_call_event_end(
    call_id: int,
    *,
    expected_capture_session_id: str,
    expected_schedule_revision: int,
    expected_event_date: object,
    expected_event_url: str,
    evidence_path: str,
    evidence_sha256: str,
    evidence_capture_session_id: str | None = None,
    evidence_attempt_path: str | None = None,
    evidence_attempt_sha256: str | None = None,
) -> Dict[str, Any]:
    """Stop retrying a proven-ended event without asserting complete coverage.

    This retrospective reconciliation is separate from normal successful STT
    completion. It never edits transcript rows or manufactures a success marker.
    The caller must first stop active work; fresh leases or running captures
    reject reconciliation even when an operator has reviewed the evidence.
    """
    def rejected(reason: str, **extra: Any) -> Dict[str, Any]:
        return {'recorded': False, 'reason': reason, **extra}

    proof = _load_retrospective_event_end(evidence_path, evidence_sha256)
    wanted_day = policies._coerce_schedule_date(expected_event_date)
    session_id = str(expected_capture_session_id or '').strip()
    evidence_session = str(evidence_capture_session_id or session_id).strip()
    expected_url = _event_end_url(expected_event_url)
    if (not proof or not wanted_day or not session_id or len(session_id) > 128
            or not evidence_session or len(evidence_session) > 128 or not expected_url):
        return rejected('invalid_end_evidence')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        revision = int(expected_schedule_revision)
        if not isinstance(proof.get('observed_at'), str) or not proof['observed_at'].strip():
            return rejected('invalid_end_evidence')
        observed = schedules._utc_naive(proof['observed_at'])
        if (revision < 0 or int(proof['schedule_revision']) != revision
                or proof['capture_session_id'] != evidence_session
                or policies._coerce_schedule_date(proof['target_date']) != wanted_day
                or _event_end_url(proof['event_url']) != expected_url
                or observed > now + timedelta(seconds=5)
                or observed < datetime.combine(wanted_day, datetime.min.time()) - timedelta(hours=14)):
            return rejected('evidence_identity_mismatch')
    except (KeyError, TypeError, ValueError, OverflowError):
        return rejected('invalid_end_evidence')

    # A retry may already have started the same event's replay. Earlier live
    # end evidence must retain its own session identity, never be relabelled as
    # evidence from the new session. A hashed original attempt binds lineage.
    if evidence_session != session_id:
        try:
            attempt_path = Path(evidence_attempt_path or '')
            if (not attempt_path.is_absolute()
                    or not re.fullmatch(r'[0-9a-f]{64}', str(evidence_attempt_sha256 or ''))
                    or not 0 < attempt_path.stat().st_size <= 65536
                    or not any(Path(source['path']).resolve() == attempt_path.resolve()
                               and source['sha256'] == evidence_attempt_sha256
                               for source in proof['sources'])):
                return rejected('missing_original_attempt_lineage')
            attempt_raw = attempt_path.read_bytes()
            if hashlib.sha256(attempt_raw).hexdigest() != evidence_attempt_sha256:
                return rejected('original_attempt_hash_changed')
            attempt = json.loads(attempt_raw)
            if (not isinstance(attempt, dict) or int(attempt.get('call_id', -1)) != int(call_id)
                    or attempt.get('capture_session_id') != evidence_session
                    or int(attempt.get('schedule_revision', -1)) != revision
                    or policies._coerce_schedule_date(attempt.get('event_date')) != wanted_day
                    or policies._normalized_schedule_ticker(attempt.get('ticker')) != policies._normalized_schedule_ticker(proof.get('ticker'))
                    or not str(attempt.get('attempt_id') or '').strip()
                    or not isinstance(attempt.get('created_at'), str)
                    or schedules._utc_naive(attempt['created_at']) > observed):
                return rejected('original_attempt_identity_mismatch')
        except (OSError, KeyError, ValueError, TypeError, OverflowError):
            return rejected('invalid_original_attempt_lineage')

    schema.ensure_schedule_time_schema()
    schema.ensure_transcript_archive_schema()
    with connection.engine.begin() as conn:
        row = conn.execute(text('SELECT * FROM calls WHERE id = :call_id FOR UPDATE'),
                           {'call_id': call_id}).mappings().first()
        if not row:
            return rejected('call_not_found')
        prior_audit = {}
        if row.get('status') == 'ended':
            try:
                prior_audit = json.loads(row.get('capture_last_error') or '{}')
            except (ValueError, TypeError):
                pass
        repeated_lineage = bool(
            row.get('status') == 'ended' and row.get('capture_session_id') == evidence_session
            and isinstance(prior_audit, dict) and prior_audit.get('sha256') == evidence_sha256
            and prior_audit.get('superseded_capture_session_id') == session_id
            and prior_audit.get('canonical_capture_session_id') == evidence_session
        )
        if ((row.get('capture_session_id') != session_id and not repeated_lineage)
                or int(row.get('schedule_revision') or 0) != revision
                or policies._coerce_schedule_date(row.get('webcast_date') or row.get('earning_at')) != wanted_day
                or policies._normalized_schedule_ticker(row.get('ticker')) != policies._normalized_schedule_ticker(proof.get('ticker'))
                or row.get('schedule_superseded_by')
                or expected_url not in {_event_end_url(row.get('event_url')), _event_end_url(row.get('webcast_url'))}):
            return rejected('current_call_identity_changed')
        if row.get('scheduled_at_utc') and observed < schedules._utc_naive(row['scheduled_at_utc']):
            return rejected('end_precedes_scheduled_start')
        if row.get('status') == 'running':
            return rejected('active_capture')
        for field in ('capture_lease_until', 'stream_probe_lease_until'):
            if row.get(field) and schedules._utc_naive(row[field]) > now:
                return rejected('active_lease', lease_kind=field)
        if row.get('status') == 'ended':
            return {'recorded': True, 'reason': 'already_ended', 'status': 'ended', 'coverage': proof['coverage']}
        if row.get('status') not in {'upcoming', 'live', 'failed'}:
            return rejected('call_not_retryable', status=row.get('status'))

        # A reviewed transcript closing must still be the latest substantive
        # archived speech in this exact session. Preserve only recognized
        # non-speech artifacts; even short renewed speech invalidates closing.
        if proof['evidence_kind'] == 'operator_closing':
            from ..live_end import is_non_speech_fragment
            tail = conn.execute(text('''
                SELECT sequence_no, text_chunk, target_identity_verified
                FROM transcript_segments
                WHERE call_id = :session_id AND sequence_no >= :sequence
                ORDER BY sequence_no
            '''), {'session_id': evidence_session, 'sequence': int(proof['terminal_sequence'])}).mappings().all()
            if (not tail or int(tail[0]['sequence_no']) != int(proof['terminal_sequence'])
                    or str(tail[0]['text_chunk']).strip() != str(proof['evidence']).strip()
                    or any(not is_non_speech_fragment(str(item['text_chunk'])) for item in tail[1:])
                    or not any(item.get('target_identity_verified') for item in tail)):
                return rejected('transcript_closing_not_terminal')
        summary = conn.execute(text('''
            SELECT COUNT(*) AS segment_count,
                   COALESCE(SUM(CHAR_LENGTH(TRIM(text_chunk))), 0) AS text_character_count
            FROM transcript_segments WHERE call_id = :session_id
        '''), {'session_id': evidence_session}).mappings().one()
        audit = json.dumps({'code': 'EVENT_ENDED_CAPTURE_COVERAGE_UNVERIFIED',
                            'coverage': proof['coverage'], 'kind': proof['evidence_kind'],
                            'artifact': str(Path(evidence_path)), 'sha256': evidence_sha256,
                            'schedule_revision': revision, 'event_date': wanted_day.isoformat(),
                            'observed_at': observed.isoformat(),
                            'superseded_capture_session_id': session_id if evidence_session != session_id else None,
                            'canonical_capture_session_id': evidence_session,
                            'original_attempt': evidence_attempt_path if evidence_session != session_id else None,
                            'original_attempt_sha256': evidence_attempt_sha256 if evidence_session != session_id else None,
                            'superseded_capture_manifest_path': row.get('capture_manifest_path') if evidence_session != session_id else None}, sort_keys=True)
        conn.execute(text('''
            UPDATE calls SET status = 'ended', stream_probe_status = 'event_ended',
                stream_probe_lease_owner = NULL, stream_probe_lease_until = NULL,
                stream_probe_heartbeat_at = NULL, stream_probe_retry_not_before = NULL,
                stream_probe_retry_reason = 'event_ended', last_stream_probe_error = :audit,
                capture_lease_owner = NULL, capture_lease_until = NULL,
                capture_started_at = NULL, capture_heartbeat_at = NULL,
                capture_previous_status = NULL, capture_retry_not_before = NULL,
                capture_last_error = :audit, capture_session_id = :evidence_session,
                capture_manifest_path = :capture_manifest_path
            WHERE id = :call_id AND schedule_revision = :revision
              AND capture_session_id = :session_id AND status IN ('upcoming', 'live', 'failed')
        '''), {'call_id': call_id, 'revision': revision, 'session_id': session_id, 'audit': audit,
               'evidence_session': evidence_session,
               'capture_manifest_path': row.get('capture_manifest_path') if evidence_session == session_id else None})
        return {'recorded': True, 'reason': 'verified_event_ended', 'status': 'ended',
                'coverage': proof['coverage'], 'segment_count': int(summary['segment_count']),
                'text_character_count': int(summary['text_character_count']),
                'canonical_capture_session_id': evidence_session}


def requeue_failed_call_capture(
    call_id: int,
    error: str | None = None,
    *,
    capture_session_id: str | None = None,
) -> bool:
    """Release a failed live capture back to the date watcher when still retryable.

    A browser or PulseAudio process is transiently fragile. A non-zero exit must
    not make a still-live earnings call disappear from the watcher permanently.
    `DATE_STREAM_CAPTURE_MAX_ATTEMPTS=0` keeps retrying until the event leaves
    its normal date/time window; a positive value is an explicit safety cap.
    """
    schema.ensure_schedule_time_schema()
    owner = _pipeline_worker_id()
    safe_error = redaction.redact_sensitive_text((error or "capture process failed")[:1000])
    session_filter = ""
    params: Dict[str, Any] = {"call_id": call_id, "owner": owner}
    if capture_session_id:
        session_filter = " AND capture_session_id = :capture_session_id"
        params["capture_session_id"] = str(capture_session_id)[:128]

    with connection.engine.begin() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT status, capture_attempts, capture_previous_status
                FROM calls
                WHERE id = :call_id
                  AND capture_lease_owner = :owner
                  {session_filter}
                FOR UPDATE
                """
            ),
            params,
        ).mappings().first()
        if not row:
            return False

        attempts = int(row.get("capture_attempts") or 0)
        policy = policies.capture_retry_policy(safe_error, attempts=attempts)
        retry_minutes = max(1, int(policy["retry_delay_minutes"] or 1))
        max_attempts = max(0, int(policy["max_attempts"] or 0))
        retryable = max_attempts == 0 or attempts < max_attempts
        if retryable:
            previous_status = str(row.get("capture_previous_status") or "upcoming")
            if previous_status not in {"upcoming", "live"}:
                previous_status = "upcoming"
            result = conn.execute(
                text(
                    f"""
                    UPDATE calls
                    SET status = :status,
                        capture_lease_owner = NULL,
                        capture_lease_until = NULL,
                        capture_started_at = NULL,
                        capture_heartbeat_at = NULL,
                        capture_previous_status = NULL,
                        capture_retry_not_before = DATE_ADD(
                            UTC_TIMESTAMP(), INTERVAL {retry_minutes} MINUTE
                        ),
                        capture_last_error = :error,
                        stream_probe_status = 'pending',
                        last_stream_probe_error = :error
                    WHERE id = :call_id
                      AND capture_lease_owner = :owner
                      {session_filter}
                    """
                ),
                {
                    **params,
                    "status": previous_status,
                    "error": safe_error,
                },
            )
            return result.rowcount == 1

        conn.execute(
            text(
                f"""
                UPDATE calls
                SET status = 'failed',
                    capture_lease_owner = NULL,
                    capture_lease_until = NULL,
                    capture_heartbeat_at = NULL,
                    capture_previous_status = NULL,
                    capture_retry_not_before = NULL,
                    capture_last_error = :error
                WHERE id = :call_id
                  AND capture_lease_owner = :owner
                  {session_filter}
                """
            ),
            {**params, "error": safe_error},
        )
        return False


def recover_stale_stream_operations(
    stale_minutes: int | None = None,
    *,
    recover_local_orphans: bool = False,
) -> Dict[str, int]:
    """Return expired leases, plus provably dead local owners, to retryable states.

    The normal path remains conservative for workers owned by another machine:
    their lease/heartbeat must become stale.  At process startup we may also
    reclaim an owner recorded for this host when its PID is gone (or the PID was
    reused with a different process-start token), avoiding a needless 20-minute
    blackout after a local container/process restart.
    """
    schema.ensure_schedule_time_schema()
    stale = max(
        1,
        int(stale_minutes)
        if stale_minutes is not None
        else policies._env_int("DATE_STREAM_STALE_LEASE_MINUTES", 20),
    )
    with connection.engine.begin() as conn:
        probe_orphans: list[dict[str, Any]] = []
        capture_orphans: list[dict[str, Any]] = []
        if recover_local_orphans:
            probe_orphans = [
                dict(row._mapping)
                for row in conn.execute(
                    text("""
                        SELECT id, stream_probe_lease_owner AS owner
                        FROM calls
                        WHERE stream_probe_status = 'probing'
                          AND stream_probe_lease_owner IS NOT NULL
                    """)
                )
                if _is_dead_local_worker_owner(row._mapping.get("owner"))
            ]
            capture_orphans = [
                dict(row._mapping)
                for row in conn.execute(
                    text("""
                        SELECT id, capture_lease_owner AS owner
                        FROM calls
                        WHERE status = 'running'
                          AND capture_lease_owner IS NOT NULL
                    """)
                )
                if _is_dead_local_worker_owner(row._mapping.get("owner"))
            ]
        probe_result = conn.execute(
            text(f"""
                UPDATE calls
                SET stream_probe_status = 'pending',
                    stream_probe_lease_owner = NULL,
                    stream_probe_lease_until = NULL,
                    stream_probe_heartbeat_at = NULL,
                    last_stream_probe_error = 'stale probe lease recovered'
                WHERE stream_probe_status = 'probing'
                  AND (
                      stream_probe_lease_until IS NULL
                      OR stream_probe_lease_until <= UTC_TIMESTAMP()
                      OR stream_probe_heartbeat_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL {stale} MINUTE)
                  )
            """),
            {},
        )
        capture_result = conn.execute(
            text(f"""
                UPDATE calls
                SET status = COALESCE(NULLIF(capture_previous_status, ''), 'upcoming'),
                    capture_lease_owner = NULL,
                    capture_lease_until = NULL,
                    capture_started_at = NULL,
                    capture_heartbeat_at = NULL,
                    capture_previous_status = NULL,
                    capture_retry_not_before = UTC_TIMESTAMP(),
                    capture_last_error = 'stale capture lease recovered',
                    stream_probe_status = 'pending',
                    last_stream_probe_error = 'stale capture lease recovered'
                WHERE status = 'running'
                  AND (
                      capture_lease_until IS NULL
                      OR capture_lease_until <= UTC_TIMESTAMP()
                      OR capture_heartbeat_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL {stale} MINUTE)
                  )
            """),
            {},
        )
        recovered_probes = int(probe_result.rowcount or 0)
        recovered_captures = int(capture_result.rowcount or 0)
        for orphan in probe_orphans:
            result = conn.execute(
                text("""
                    UPDATE calls
                    SET stream_probe_status = 'pending',
                        stream_probe_lease_owner = NULL,
                        stream_probe_lease_until = NULL,
                        stream_probe_heartbeat_at = NULL,
                        last_stream_probe_error = 'local probe lease recovered after restart'
                    WHERE id = :call_id
                      AND stream_probe_status = 'probing'
                      AND stream_probe_lease_owner = :owner
                """),
                {"call_id": orphan["id"], "owner": orphan["owner"]},
            )
            recovered_probes += int(result.rowcount or 0)
        for orphan in capture_orphans:
            result = conn.execute(
                text("""
                    UPDATE calls
                    SET status = COALESCE(NULLIF(capture_previous_status, ''), 'upcoming'),
                        capture_lease_owner = NULL,
                        capture_lease_until = NULL,
                        capture_started_at = NULL,
                        capture_heartbeat_at = NULL,
                        capture_previous_status = NULL,
                        capture_retry_not_before = UTC_TIMESTAMP(),
                        capture_last_error = 'local capture lease recovered after restart',
                        stream_probe_status = 'pending',
                        last_stream_probe_error = 'local capture lease recovered after restart'
                    WHERE id = :call_id
                      AND status = 'running'
                      AND capture_lease_owner = :owner
                """),
                {"call_id": orphan["id"], "owner": orphan["owner"]},
            )
            recovered_captures += int(result.rowcount or 0)
    return {
        "probes": recovered_probes,
        "captures": recovered_captures,
    }


def _linux_process_start_token(pid: int) -> str | None:
    """Return Linux /proc start time so a reused PID is not mistaken for a worker."""
    try:
        contents = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = contents.rsplit(")", 1)[1].split()
        # `/proc/<pid>/stat` field 22 is process start time.  `fields` starts
        # at field 3 because the process name may itself contain parentheses.
        return fields[19]
    except (FileNotFoundError, IndexError, OSError):
        return None


def _local_worker_owner_details(owner: str | None) -> tuple[str, int, str | None] | None:
    """Parse current and legacy worker IDs without trusting foreign owners."""
    value = str(owner or "").strip()
    if not value:
        return None
    parts = value.rsplit("|", 3)
    if len(parts) == 4 and parts[2].isdigit():
        return parts[1], int(parts[2]), parts[3] or None
    host, separator, raw_pid = value.rpartition(":")
    if separator and host and raw_pid.isdigit():
        return host, int(raw_pid), None
    return None


def _is_dead_local_worker_owner(owner: str | None) -> bool:
    """Return true only for a missing or replaced process on this host."""
    details = _local_worker_owner_details(owner)
    if not details:
        return False
    hostname, pid, expected_start_token = details
    if hostname != socket.gethostname():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return False

    if expected_start_token:
        actual_start_token = _linux_process_start_token(pid)
        return actual_start_token is not None and actual_start_token != expected_start_token
    return False


def _pipeline_worker_id() -> str:
    """Use a stable-in-process, restart-distinct identity for DB leases."""
    hostname = socket.gethostname()
    configured = (os.getenv("PIPELINE_WORKER_ID", "").strip() or hostname)[:32]
    start_token = _linux_process_start_token(os.getpid()) or ""
    return f"{configured}|{hostname}|{os.getpid()}|{start_token}"


def update_call_status(call_id: int, status: str):
    """STT 워커 상태를 calls 테이블에 반영한다."""
    owner = _pipeline_worker_id()
    query = text("""
        UPDATE calls
        SET status = :status,
            capture_previous_status = CASE
                WHEN :status IN ('completed', 'failed', 'cancelled') THEN NULL
                ELSE capture_previous_status
            END,
            capture_retry_not_before = CASE
                WHEN :status IN ('completed', 'failed', 'cancelled') THEN NULL
                ELSE capture_retry_not_before
            END
        WHERE id = :call_id
          AND (
              capture_lease_owner = :owner
          )
    """)

    with connection.engine.begin() as conn:
        conn.execute(query, {"call_id": call_id, "status": status, "owner": owner})
        if status in {"completed", "failed", "cancelled"}:
            conn.execute(
                text("""
                    UPDATE calls
                    SET capture_lease_owner = NULL,
                        capture_lease_until = NULL,
                        capture_heartbeat_at = NULL,
                        capture_previous_status = NULL,
                        capture_retry_not_before = NULL
                    WHERE id = :call_id
                      AND (
                          capture_lease_owner = :owner
                      )
                """),
                {"call_id": call_id, "owner": owner},
            )
