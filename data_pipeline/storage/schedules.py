"""Schedule reconciliation and official IR verification."""

from sqlalchemy import text
from contextlib import nullcontext
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo
from . import connection, policies, redaction, schema
from ..collectors.schedules.event_routes import stored_event_kind_conflict
from ..collectors.schedules.route_retention import authenticated_route, retained_route_fields, event_day
from ..collectors.schedules.clock_reconciliation import reconcile_clock_observations


def save_earnings_schedules(
    schedules: List[Dict],
    *,
    observed_at: datetime | None = None,
):
    """Store Yahoo dates and record the exact broad-calendar observation time."""
    if not schedules:
        return
    schema.ensure_schedule_time_schema()
    observed_at = observed_at or datetime.utcnow()
    observed_at = _utc_naive(observed_at).replace(microsecond=0)

    # A date correction must reset stale discovery state, but never while the
    # same row owns an active browser probe or STT capture. The next refresh
    # applies the correction after the operation releases its lease.
    reset_changed_schedule = text("""
        UPDATE calls
        SET webcast_date = NULL,
            scheduled_at_utc = NULL,
            source_timezone = NULL,
            event_url = NULL,
            webcast_url = NULL,
            video_url = NULL,
            schedule_source = NULL,
            schedule_evidence = NULL,
            time_verification_status = 'unverified',
            time_verified_at = NULL,
            stream_probe_status = 'pending',
            stream_probe_attempts = 0,
            last_stream_probe_at = NULL,
            last_stream_probe_error = NULL,
            stream_probe_retry_not_before = NULL,
            stream_probe_retry_reason = NULL,
            stream_detected_at = NULL,
            stream_probe_lease_owner = NULL,
            stream_probe_lease_until = NULL,
            stream_probe_heartbeat_at = NULL,
            capture_attempts = 0,
            capture_previous_status = NULL,
            capture_lease_owner = NULL,
            capture_lease_until = NULL,
            capture_started_at = NULL,
            capture_heartbeat_at = NULL,
            capture_manifest_path = NULL,
            capture_session_id = NULL,
            capture_retry_not_before = NULL,
            capture_last_error = NULL,
            schedule_refresh_requested_at = NULL,
            schedule_refresh_attempts = 0,
            schedule_refresh_last_error = NULL,
            schedule_enrichment_last_attempt_at = NULL,
            schedule_enrichment_retry_not_before = NULL,
            schedule_enrichment_failure_kind = NULL,
            schedule_enrichment_last_error = NULL,
            schedule_discovery_fingerprint = NULL,
            schedule_discovery_checked_at = NULL,
            schedule_discovery_changed_at = NULL,
            schedule_revalidation_status = 'provisional_watch',
            schedule_revalidation_reason = 'yahoo_date_changed',
            schedule_revalidation_evidence = NULL,
            status = 'upcoming',
            earning_at = :earning_date,
            schedule_revision = schedule_revision + 1,
            schedule_observed_at = :observed_at,
            schedule_last_yahoo_seen_at = :observed_at
        WHERE ticker = :ticker
          AND call_year = :call_year
          AND quarter = :quarter
          AND status <> 'running'
          AND status NOT IN ('completed', 'ended')
          AND schedule_superseded_by IS NULL
          AND stream_probe_status <> 'probing'
          AND COALESCE(schedule_source, '') NOT LIKE 'official%'
          AND (schedule_observed_at IS NULL OR schedule_observed_at <= :observed_at)
          AND NOT (earning_at <=> :earning_date)
    """)
    upsert_schedule = text("""
        INSERT INTO calls (
            ticker, earning_at, call_year, quarter, status, schedule_last_yahoo_seen_at
        )
        VALUES (:ticker, :earning_date, :call_year, :quarter, 'upcoming', :observed_at)
        ON DUPLICATE KEY UPDATE
            status = IF(
                status IN ('completed', 'ended', 'running', 'live') OR schedule_superseded_by IS NOT NULL, status, 'upcoming'
            ),
            earning_at = IF(
                status = 'running' OR stream_probe_status = 'probing'
                    OR status IN ('completed', 'ended') OR schedule_superseded_by IS NOT NULL
                    OR COALESCE(schedule_source, '') LIKE 'official%'
                    OR schedule_observed_at > :observed_at,
                earning_at,
                VALUES(earning_at)
            ),
            schedule_last_yahoo_seen_at = GREATEST(
                COALESCE(schedule_last_yahoo_seen_at, VALUES(schedule_last_yahoo_seen_at)),
                VALUES(schedule_last_yahoo_seen_at))
    """)

    with connection.engine.begin() as conn:
        for item in schedules:
            item = dict(item)
            # 캘린더 날짜를 기반으로 연도/분기 계산 로직 추가 가능
            item['call_year'] = item['earning_date'].year
            item['quarter'] = f"Q{(item['earning_date'].month-1)//3 + 1}"
            item['observed_at'] = observed_at
            before = conn.execute(text('''
                SELECT * FROM calls WHERE ticker = :ticker AND call_year = :call_year
                    AND quarter = :quarter FOR UPDATE
            '''), item).mappings().first()
            conn.execute(reset_changed_schedule, item)
            conn.execute(upsert_schedule, item)
            if before:
                after = conn.execute(text('SELECT * FROM calls WHERE id = :call_id'),
                                     {'call_id': before['id']}).mappings().first()
                if after and after['schedule_revision'] != before['schedule_revision']:
                    _append_history(conn, dict(before), dict(after), 'broad_calendar_date_changed', observed_at)
    print(f"💾 [Schedules] {len(schedules)}개 일정 업데이트 완료.")


def reconcile_near_term_schedule_sources(
    nasdaq_schedules: List[Dict[str, Any]],
    *,
    yahoo_observed_at: datetime,
    nasdaq_fetched_dates: set[date],
    start_date: date,
    days_ahead: int,
    observed_at: datetime | None = None,
) -> Dict[str, int]:
    """Keep conflicting third-party dates watchable until issuer IR resolves them.

    Yahoo remains the broad release-date source and Nasdaq is corroborating
    evidence, not an authority that may overwrite the stored day. A failed
    request never counts as an empty day, and a disagreement widens the watch
    window instead of suppressing a real call.
    """
    schema.ensure_schedule_time_schema()
    start_date = policies._coerce_schedule_date(start_date) or datetime.utcnow().date()
    end_date = start_date + timedelta(days=max(1, int(days_ahead)))
    observed_at = observed_at or datetime.utcnow()
    observed_at = _utc_naive(observed_at).replace(microsecond=0)
    yahoo_observed_at = yahoo_observed_at.replace(tzinfo=None, microsecond=0)

    fetched_dates = {
        parsed
        for value in nasdaq_fetched_dates
        if (parsed := policies._coerce_schedule_date(value)) is not None
    }
    nasdaq_by_ticker: dict[str, list[date]] = {}
    for item in nasdaq_schedules:
        ticker = policies._normalized_schedule_ticker(item.get("ticker"))
        earning_date = policies._coerce_schedule_date(item.get("earning_date"))
        if not ticker or earning_date is None:
            continue
        dates = nasdaq_by_ticker.setdefault(ticker, [])
        if earning_date not in dates:
            dates.append(earning_date)
    for dates in nasdaq_by_ticker.values():
        dates.sort()

    summary = {
        "nasdaq_events": sum(len(dates) for dates in nasdaq_by_ticker.values()),
        "source_matches": 0,
        "source_recovered": 0,
        "date_mismatches": 0,
        "yahoo_missing": 0,
        "nasdaq_only": 0,
    }
    select_rows = text("""
        SELECT id, ticker, earning_at, schedule_last_yahoo_seen_at,
               schedule_revalidation_reason
        FROM calls
        WHERE status = 'upcoming'
          AND schedule_superseded_by IS NULL
          AND earning_at >= :start_date
          AND earning_at < :end_date
        ORDER BY ticker ASC, earning_at ASC
    """)
    mark_nasdaq_seen = text("""
        UPDATE calls
        SET schedule_last_nasdaq_seen_at = :observed_at
        WHERE id = :call_id
          AND status = 'upcoming'
    """)
    mark_revalidation = text("""
        UPDATE calls
        SET schedule_revalidation_status = 'provisional_watch',
            schedule_revalidation_reason = :reason,
            schedule_revalidation_evidence = :evidence,
            schedule_last_nasdaq_seen_at = COALESCE(
                :nasdaq_seen_at, schedule_last_nasdaq_seen_at
            )
        WHERE id = :call_id
          AND status = 'upcoming'
          AND COALESCE(schedule_source, '') NOT LIKE 'official%'
          AND COALESCE(schedule_revalidation_reason, '') <> 'official_page_date_mismatch'
    """)
    clear_recovered_yahoo_missing = text("""
        UPDATE calls
        SET schedule_revalidation_status = 'clear',
            schedule_revalidation_reason = NULL,
            schedule_revalidation_evidence = NULL
        WHERE id = :call_id
          AND status = 'upcoming'
          AND schedule_revalidation_reason IN (
              'yahoo_source_missing', 'date_mismatch', 'nasdaq_only',
              'yahoo_date_changed'
          )
    """)
    mark_date_mismatch = text("""
        UPDATE calls
        SET schedule_revalidation_status = 'provisional_watch',
            schedule_revalidation_reason = 'date_mismatch',
            schedule_revalidation_evidence = :evidence,
            schedule_last_nasdaq_seen_at = :observed_at
        WHERE id = :call_id
          AND status = 'upcoming'
          AND COALESCE(schedule_source, '') NOT LIKE 'official%'
          AND COALESCE(schedule_revalidation_reason, '') <> 'official_page_date_mismatch'
    """)
    upsert_nasdaq_only = text("""
        INSERT INTO calls (
            ticker, earning_at, call_year, quarter, status,
            time_verification_status, schedule_revalidation_status,
            schedule_revalidation_reason, schedule_last_nasdaq_seen_at,
            schedule_revalidation_evidence
        )
        VALUES (
            :ticker, :earning_date, :call_year, :quarter, 'upcoming',
            'unverified', 'provisional_watch', 'nasdaq_only', :observed_at, :evidence
        )
        ON DUPLICATE KEY UPDATE
            earning_at = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR status IN ('completed', 'ended') OR schedule_superseded_by IS NOT NULL
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                earning_at, VALUES(earning_at)
            ),
            scheduled_at_utc = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                scheduled_at_utc, NULL
            ),
            source_timezone = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                source_timezone, NULL
            ),
            event_url = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                event_url, NULL
            ),
            webcast_url = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                webcast_url, NULL
            ),
            video_url = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing',
                video_url, NULL
            ),
            schedule_evidence = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                schedule_evidence, NULL
            ),
            time_verification_status = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                time_verification_status, 'unverified'
            ),
            time_verified_at = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                time_verified_at, NULL
            ),
            schedule_revalidation_status = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL
                    OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%'
                    OR schedule_revalidation_reason = 'official_page_date_mismatch',
                schedule_revalidation_status, 'provisional_watch'
            ),
            schedule_revalidation_reason = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL
                    OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%'
                    OR schedule_revalidation_reason = 'official_page_date_mismatch',
                schedule_revalidation_reason, 'nasdaq_only'
            ),
            schedule_source = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing'
                    OR COALESCE(schedule_source, '') LIKE 'official%',
                schedule_source, NULL
            ),
            schedule_last_nasdaq_seen_at = VALUES(schedule_last_nasdaq_seen_at),
            schedule_revalidation_evidence = IF(
                status IN ('running', 'completed', 'ended') OR schedule_superseded_by IS NOT NULL OR stream_probe_status = 'probing',
                schedule_revalidation_evidence,
                VALUES(schedule_revalidation_evidence)
            )
    """)

    with connection.engine.begin() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                select_rows,
                {"start_date": start_date, "end_date": end_date},
            ).mappings()
        ]
        rows_by_ticker: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            rows_by_ticker.setdefault(policies._normalized_schedule_ticker(row["ticker"]), []).append(row)

        for row in rows:
            ticker = policies._normalized_schedule_ticker(row["ticker"])
            stored_date = policies._coerce_schedule_date(row["earning_at"])
            if stored_date is None:
                continue
            nasdaq_dates = nasdaq_by_ticker.get(ticker, [])
            yahoo_seen_at = row.get("schedule_last_yahoo_seen_at")
            yahoo_seen = isinstance(yahoo_seen_at, datetime) and yahoo_seen_at >= yahoo_observed_at

            if nasdaq_dates:
                candidate_date = min(
                    nasdaq_dates,
                    key=lambda value: abs((value - stored_date).days),
                )
                if candidate_date == stored_date:
                    conn.execute(
                        mark_nasdaq_seen,
                        {"call_id": row["id"], "observed_at": observed_at},
                    )
                    summary["source_matches"] += 1
                    if yahoo_seen:
                        if row.get("schedule_revalidation_reason") in {
                            "yahoo_source_missing",
                            "date_mismatch",
                            "nasdaq_only",
                            "yahoo_date_changed",
                        }:
                            conn.execute(
                                clear_recovered_yahoo_missing,
                                {"call_id": row["id"]},
                            )
                            summary["source_recovered"] += 1
                        continue
                    reason = "yahoo_source_missing"
                else:
                    evidence = json.dumps(
                        {
                            "reason": "date_mismatch",
                            "database_date": stored_date.isoformat(),
                            "nasdaq_date": candidate_date.isoformat(),
                            "yahoo_observed_at": yahoo_observed_at.isoformat(),
                        },
                        sort_keys=True,
                    )
                    conn.execute(
                        mark_date_mismatch,
                        {
                            "call_id": row["id"],
                            "observed_at": observed_at,
                            "evidence": evidence,
                        },
                    )
                    summary["date_mismatches"] += 1
                    continue
            elif stored_date in fetched_dates and not yahoo_seen:
                reason = "yahoo_source_missing"
            else:
                continue

            evidence = json.dumps(
                {
                    "reason": reason,
                    "database_date": stored_date.isoformat(),
                    "yahoo_observed_at": yahoo_observed_at.isoformat(),
                    "nasdaq_date": candidate_date.isoformat() if nasdaq_dates else None,
                },
                sort_keys=True,
            )
            conn.execute(
                mark_revalidation,
                {
                    "call_id": row["id"],
                    "reason": reason,
                    "evidence": evidence,
                    "nasdaq_seen_at": observed_at if nasdaq_dates else None,
                },
            )
            summary["yahoo_missing"] += 1

        for ticker, dates in nasdaq_by_ticker.items():
            if ticker in rows_by_ticker:
                continue
            for earning_date in dates:
                evidence = json.dumps(
                    {
                        "reason": "nasdaq_only",
                        "nasdaq_date": earning_date.isoformat(),
                        "yahoo_observed_at": yahoo_observed_at.isoformat(),
                    },
                    sort_keys=True,
                )
                conn.execute(
                    upsert_nasdaq_only,
                    {
                        "ticker": ticker,
                        "earning_date": earning_date,
                        "call_year": earning_date.year,
                        "quarter": f"Q{(earning_date.month - 1) // 3 + 1}",
                        "observed_at": observed_at,
                        "evidence": evidence,
                    },
                )
                summary["nasdaq_only"] += 1

    return summary


def update_stream_link(ticker: str, video_url: str):
    """유튜브 등에서 찾은 실시간 링크를 기존 일정에 업데이트"""
    query = text("""
        UPDATE calls 
        SET video_url = :video_url, status = 'live'
        WHERE ticker = :ticker
          AND status = 'upcoming'
          AND schedule_revalidation_status IN ('clear', 'provisional_watch')
        ORDER BY earning_at ASC LIMIT 1
    """)
    
    with connection.engine.begin() as conn:
        conn.execute(query, {"ticker": ticker, "video_url": video_url})


def update_call_video_url(call_id: int, video_url: str):
    """브라우저 자동화로 확보한 실제 미디어 URL을 콜 레코드에 저장한다."""
    query = text("""
        UPDATE calls
        SET video_url = :video_url
        WHERE id = :call_id
    """)

    with connection.engine.begin() as conn:
        conn.execute(query, {"call_id": call_id, "video_url": video_url})


def get_imminent_calls(minutes_ahead: int = 5, grace_minutes: int = 1) -> List[Dict]:
    """STT 워커가 처리해야 할 임박한 어닝콜을 조회한다."""
    schema.ensure_schedule_time_schema()
    query = text("""
        SELECT
            c.id,
            c.ticker,
            c.earning_at,
            c.webcast_date,
            c.scheduled_at_utc,
            c.call_year,
            c.quarter,
            c.status,
            c.video_url,
            s.company_name,
            s.ir_url,
            c.event_url,
            c.webcast_url
        FROM calls c
        LEFT JOIN stocks s ON s.ticker = c.ticker
        WHERE c.status IN ('upcoming', 'live')
          AND c.schedule_superseded_by IS NULL
          AND c.schedule_revalidation_status IN ('clear', 'provisional_watch')
          AND c.time_verification_status = 'verified'
          AND c.scheduled_at_utc BETWEEN
              DATE_SUB(NOW(), INTERVAL :grace_minutes MINUTE)
              AND DATE_ADD(NOW(), INTERVAL :minutes_ahead MINUTE)
        ORDER BY c.scheduled_at_utc ASC
    """)

    with connection.engine.connect() as conn:
        result = conn.execute(
            query,
            {
                "minutes_ahead": minutes_ahead,
                "grace_minutes": grace_minutes,
            },
        )
        return [dict(row._mapping) for row in result]


def get_calls_missing_verified_time(
    limit: int | None = None,
    days_ahead: int | None = None,
    *,
    reference_time_utc: datetime | None = None,
) -> List[Dict[str, Any]]:
    """Recheck near-event starts frequently and use the watcher's local day."""
    schema.ensure_schedule_time_schema()
    now = reference_time_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    event_day = now.astimezone(ZoneInfo(os.getenv(
        "DATE_STREAM_WATCH_TIMEZONE", "America/New_York",
    ))).date()
    now_utc = now.replace(tzinfo=None)
    reverify_hours = policies._env_int("SCHEDULE_TIME_REVERIFY_HOURS", 24)
    near_reverify_minutes = policies._env_int("SCHEDULE_TIME_NEAR_REVERIFY_MINUTES", 10)
    params: Dict[str, Any] = {
        "event_day": event_day,
        "near_day_end": event_day + timedelta(days=2),
        "uncertain_start_day": event_day - timedelta(days=policies._nonnegative_env_int(
            "DATE_STREAM_UNCERTAIN_DATE_GRACE_DAYS", 2,
        )),
        "now_utc": now_utc,
        "recent_start": now_utc - timedelta(minutes=policies._env_int(
            "DATE_STREAM_NEAR_END_MINUTES", 180, minimum=0,
        )),
        "stale_before": now_utc - timedelta(hours=reverify_hours),
        "near_stale_before": now_utc - timedelta(minutes=near_reverify_minutes),
    }
    invalidate_non_earnings_schedule_evidence(
        reference_time_utc=now, days_ahead=days_ahead or 14)
    query = """
        SELECT c.id, c.ticker, c.earning_at, c.webcast_date, c.scheduled_at_utc,
               c.event_url, c.webcast_url, c.source_timezone, c.schedule_source, c.schedule_evidence,
               c.schedule_discovery_fingerprint, c.schedule_discovery_checked_at,
               c.call_year, c.quarter, c.schedule_revision, c.schedule_observed_at,
               c.verified_fiscal_year, c.verified_fiscal_quarter,
               c.official_event_key, c.official_event_identity,
               c.time_verification_status, c.time_verified_at,
               c.schedule_revalidation_status, c.schedule_revalidation_reason,
               c.schedule_revalidation_evidence,
               c.schedule_enrichment_last_attempt_at,
               c.schedule_enrichment_retry_not_before,
               c.schedule_enrichment_failure_kind,
               c.schedule_enrichment_last_error,
               s.company_name, s.ir_url
        FROM calls c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE c.status = 'upcoming'
          AND c.schedule_superseded_by IS NULL
          AND (
              COALESCE(c.webcast_date, DATE(c.earning_at)) >= :event_day
              OR (c.scheduled_at_utc >= :recent_start AND c.scheduled_at_utc <= :now_utc)
              OR (c.schedule_revalidation_status IN ('required', 'provisional_watch')
                  AND COALESCE(c.webcast_date, DATE(c.earning_at)) >= :uncertain_start_day)
          )
          AND (
              c.time_verification_status <> 'verified'
              OR c.time_verified_at IS NULL
              OR c.schedule_revalidation_status = 'required'
              OR c.time_verified_at <= :stale_before
              OR (COALESCE(c.webcast_date, DATE(c.earning_at)) < :near_day_end
                  AND c.time_verified_at <= :near_stale_before)
          )
          AND (
              c.schedule_enrichment_retry_not_before IS NULL
              OR c.schedule_enrichment_retry_not_before <= :now_utc
          )
    """
    if days_ahead is not None:
        query += " AND COALESCE(c.webcast_date, DATE(c.earning_at)) < :end_day"
        params["end_day"] = event_day + timedelta(days=max(1, int(days_ahead)))
    query += """
        ORDER BY
            CASE WHEN COALESCE(c.webcast_date, DATE(c.earning_at)) < :near_day_end THEN 0 ELSE 1 END,
            COALESCE(c.schedule_enrichment_last_attempt_at, '1970-01-01 00:00:00') ASC,
            CASE WHEN c.schedule_revalidation_status = 'required' THEN 0 ELSE 1 END,
            COALESCE(c.webcast_date, DATE(c.earning_at)) ASC, c.ticker ASC
    """
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, int(limit))
    with connection.engine.connect() as conn:
        result = conn.execute(text(query), params)
        return [dict(row._mapping) for row in result]


def get_call_schedule_context(call_id: int) -> Dict[str, Any] | None:
    """Read one call with the issuer context needed for a targeted refresh."""
    schema.ensure_schedule_time_schema()
    query = text("""
        SELECT c.id, c.ticker, c.earning_at, c.webcast_date, c.scheduled_at_utc,
               c.call_year, c.quarter, c.status, c.event_url, c.webcast_url,
               c.source_timezone, c.schedule_source, c.schedule_evidence,
               c.schedule_discovery_fingerprint, c.schedule_discovery_checked_at,
               c.stream_probe_status,
               c.stream_probe_retry_not_before, c.stream_probe_retry_reason,
               c.schedule_superseded_by, c.schedule_revision, c.schedule_observed_at,
               c.verified_fiscal_year, c.verified_fiscal_quarter,
               c.official_event_key, c.official_event_identity,
               c.time_verification_status, c.time_verified_at,
               c.schedule_revalidation_status, c.schedule_revalidation_reason,
               c.schedule_revalidation_evidence,
               c.schedule_enrichment_last_attempt_at,
               c.schedule_enrichment_retry_not_before,
               c.schedule_enrichment_failure_kind,
               c.schedule_enrichment_last_error,
               s.company_name, s.ir_url
        FROM calls c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE c.id = :call_id
    """)
    with connection.engine.connect() as conn:
        row = conn.execute(query, {"call_id": call_id}).mappings().first()
    return dict(row) if row else None


def request_schedule_refresh(call_id: int, reason: str | None = None) -> bool:
    """Deduplicate an urgent single-call schedule refresh after mismatch evidence."""
    schema.ensure_schedule_time_schema()
    cooldown_minutes = policies._env_int("DATE_STREAM_SCHEDULE_REFRESH_COOLDOWN_MINUTES", 60)
    query = text(f"""
        UPDATE calls
        SET schedule_refresh_requested_at = UTC_TIMESTAMP(),
            schedule_refresh_attempts = schedule_refresh_attempts + 1,
            schedule_refresh_last_error = :reason
        WHERE id = :call_id
          AND (
              schedule_refresh_requested_at IS NULL
              OR schedule_refresh_requested_at <= DATE_SUB(
                  UTC_TIMESTAMP(), INTERVAL {cooldown_minutes} MINUTE
              )
          )
    """)
    with connection.engine.begin() as conn:
        result = conn.execute(
            query,
            {
                "call_id": call_id,
                "reason": redaction.redact_sensitive_text(str(reason or ""))[:1000] or None,
            },
        )
        return result.rowcount == 1


def record_schedule_refresh_outcome(
    call_id: int,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    """Keep the latest urgent-refresh result visible without changing call status."""
    schema.ensure_schedule_time_schema()
    query = text("""
        UPDATE calls
        SET schedule_refresh_last_error = :error
        WHERE id = :call_id
    """)
    message = None if success else redaction.redact_sensitive_text(str(error or "refresh failed"))[:1000]
    with connection.engine.begin() as conn:
        conn.execute(query, {"call_id": call_id, "error": message})


def get_schedule_enrichment_circuit(scope: str) -> Dict[str, Any] | None:
    """Return an active provider circuit, if one survives across scheduler restarts."""
    schema.ensure_schedule_time_schema()
    query = text("""
        SELECT scope, state, failure_kind, failure_count, opened_at,
               retry_not_before, last_error
        FROM schedule_enrichment_circuits
        WHERE scope = :scope
          AND state = 'open'
          AND retry_not_before > UTC_TIMESTAMP()
    """)
    with connection.engine.connect() as conn:
        row = conn.execute(query, {"scope": str(scope)[:64]}).mappings().first()
    return dict(row) if row else None


def open_schedule_enrichment_circuit(
    scope: str,
    *,
    failure_kind: str,
    error: str | None,
    retry_minutes: int,
) -> None:
    """Persist a bounded provider cooldown so one bad key cannot burn all credits."""
    schema.ensure_schedule_time_schema()
    minutes = max(1, int(retry_minutes))
    query = text(f"""
        INSERT INTO schedule_enrichment_circuits (
            scope, state, failure_kind, failure_count, opened_at,
            retry_not_before, last_error
        ) VALUES (
            :scope, 'open', :failure_kind, 1, UTC_TIMESTAMP(),
            DATE_ADD(UTC_TIMESTAMP(), INTERVAL {minutes} MINUTE), :error
        )
        ON DUPLICATE KEY UPDATE
            state = 'open',
            failure_kind = VALUES(failure_kind),
            failure_count = failure_count + 1,
            opened_at = UTC_TIMESTAMP(),
            retry_not_before = VALUES(retry_not_before),
            last_error = VALUES(last_error)
    """)
    safe_error = redaction.redact_sensitive_text(str(error or "schedule enrichment provider failure"))[:1000]
    with connection.engine.begin() as conn:
        conn.execute(
            query,
            {
                "scope": str(scope)[:64],
                "failure_kind": str(failure_kind)[:64],
                "error": safe_error,
            },
        )


def clear_schedule_enrichment_circuit(scope: str) -> None:
    """Close a provider circuit after a later successful response."""
    schema.ensure_schedule_time_schema()
    query = text("""
        UPDATE schedule_enrichment_circuits
        SET state = 'closed',
            failure_kind = NULL,
            failure_count = 0,
            opened_at = NULL,
            retry_not_before = NULL,
            last_error = NULL
        WHERE scope = :scope
    """)
    with connection.engine.begin() as conn:
        conn.execute(query, {"scope": str(scope)[:64]})


def record_schedule_enrichment_outcome(
    call_id: int, *, failure_kind: str, error: str | None, retry_minutes: int,
    expected_revision: int | None = None, observed_at: datetime | None = None,
    route_observation: dict | None = None,
    clock_observations: list[dict] | None = None,
) -> None:
    """Network failures retain evidence; clock ambiguity can keep a proven route."""
    schema.ensure_schedule_time_schema()
    now = _utc_naive(observed_at)
    values = {
        'schedule_enrichment_last_attempt_at': now,
        'schedule_enrichment_retry_not_before': now + timedelta(minutes=max(1, int(retry_minutes))),
        'schedule_enrichment_failure_kind': str(failure_kind)[:64],
        'schedule_enrichment_last_error': redaction.redact_sensitive_text(str(error or 'schedule enrichment unavailable'))[:1000],
    }
    if failure_kind in {'ambiguous_call_time', 'ambiguous_event_identity', 'official_time_withdrawn', 'official_time_tbd',
                        'official_cancelled', 'official_postponed'}:
        values.update(scheduled_at_utc=None, source_timezone=None, time_verified_at=None,
                      time_verification_status='unverified',
                      schedule_revalidation_status='cancelled' if failure_kind == 'official_cancelled' else 'provisional_watch',
                      schedule_revalidation_reason=failure_kind,
                      schedule_revalidation_evidence=None)
        if failure_kind != 'ambiguous_call_time':
            # Revocation is a state change even when an earlier clock conflict
            # already cleared the time. Never leave its reusable route marker.
            values.update(schedule_discovery_fingerprint=None, schedule_discovery_checked_at=None)
        elif clock_observations:
            # Keep both clocks and their actual source URLs, independently of
            # the short human error column. This never authenticates a route.
            values['schedule_revalidation_evidence'] = json.dumps({
                'clock_observations': clock_observations[:12]}, default=str, sort_keys=True)
        identity = None
        if failure_kind == 'ambiguous_call_time' and route_observation:
            route = route_observation
            identity = route.get('event_identity')
            values.update(webcast_date=route.get('webcast_date'), event_url=route.get('event_url'),
                webcast_url=route.get('webcast_url'), schedule_source=route.get('source'),
                schedule_evidence=redaction.redact_sensitive_text(route.get('evidence') or '')[:3500],
                schedule_discovery_fingerprint=route.get('fingerprint'),
                schedule_discovery_checked_at=now)
        _apply_official_observation(call_id, values, reason=failure_kind,
                                   event_identity=identity,
                                   expected_revision=expected_revision, observed_at=now,
                                   clock_conflict_route=bool(route_observation and failure_kind == 'ambiguous_call_time'))
        return
    query = text("""
        UPDATE calls
        SET schedule_enrichment_last_attempt_at = :schedule_enrichment_last_attempt_at,
            schedule_enrichment_retry_not_before = :schedule_enrichment_retry_not_before,
            schedule_enrichment_failure_kind = :schedule_enrichment_failure_kind,
            schedule_enrichment_last_error = :schedule_enrichment_last_error
        WHERE id = :call_id
          AND status IN ('upcoming', 'live')
          AND COALESCE(stream_probe_status, 'pending') <> 'probing'
          AND schedule_superseded_by IS NULL
          AND (:expected_revision IS NULL OR schedule_revision = :expected_revision)
          AND (schedule_observed_at IS NULL OR schedule_observed_at <= :observed_at)
          AND (schedule_enrichment_last_attempt_at IS NULL OR schedule_enrichment_last_attempt_at <= :observed_at)
    """)
    with connection.engine.begin() as conn:
        conn.execute(query, {**values, 'call_id': call_id, 'expected_revision': expected_revision,
                             'observed_at': now})


_HISTORY_FIELDS = (
    'id', 'ticker', 'earning_at', 'call_year', 'quarter', 'webcast_date',
    'scheduled_at_utc', 'source_timezone', 'event_url', 'webcast_url',
    'schedule_source', 'schedule_evidence', 'time_verification_status',
    'time_verified_at', 'schedule_revision', 'schedule_observed_at',
    'verified_fiscal_year', 'verified_fiscal_quarter', 'official_event_key',
    'official_event_identity', 'schedule_superseded_by',
    'schedule_revalidation_status', 'schedule_revalidation_reason',
    'schedule_revalidation_evidence', 'schedule_last_nasdaq_seen_at',
    'schedule_discovery_fingerprint',
)


def _utc_naive(value: object = None) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        value = datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _history_json(row: dict) -> str:
    return json.dumps({key: row.get(key) for key in _HISTORY_FIELDS},
                      default=str, ensure_ascii=False, sort_keys=True)


def _append_history(conn, before: dict, after: dict, reason: str, observed_at: datetime) -> None:
    conn.execute(text('''
        INSERT INTO schedule_change_history
            (call_id, revision, reason, observed_at, before_json, after_json)
        VALUES (:call_id, :revision, :reason, :observed_at, :before_json, :after_json)
    '''), {'call_id': before['id'], 'revision': after['schedule_revision'],
           'reason': reason[:64], 'observed_at': observed_at,
           'before_json': _history_json(before), 'after_json': _history_json(after)})


def _normal_identity(value: object) -> dict:
    """Only issuer-verified fiscal fields become identity; calendar fields never do."""
    if not isinstance(value, dict) or value.get('identity_verified') is not True:
        return {}
    if value.get('event_type') != 'earnings_call':
        return {}
    result = dict(value)
    result['official_event_key'] = redaction.redact_sensitive_url(
        str(value.get('official_event_key') or ''))[:2048] or None
    year = value.get('fiscal_year')
    result['fiscal_year'] = int(year) if str(year or '').isdigit() and 2000 <= int(year) <= 2200 else None
    quarter = str(value.get('fiscal_quarter') or '').upper()
    result['fiscal_quarter'] = quarter if quarter in {'Q1', 'Q2', 'Q3', 'Q4'} else None
    return result


def _same_official_event(row: dict, identity: dict) -> bool:
    # Issuers sometimes reuse one /earnings-webcast URL every quarter. A key
    # match never overrides contradictory fiscal labels.
    year, quarter = identity.get('fiscal_year'), identity.get('fiscal_quarter')
    for incoming, existing in [(year, row.get('verified_fiscal_year')),
                               (quarter, row.get('verified_fiscal_quarter'))]:
        if incoming and existing and str(incoming) != str(existing):
            return False
    if year and quarter and str(row.get('verified_fiscal_year')) == str(year) and row.get('verified_fiscal_quarter') == quarter:
        return True
    key = identity.get('official_event_key')
    # A year/quarter-bearing event path is immutable enough to corroborate the
    # same event. Generic or year-only calendars cannot suppress another row.
    specific = bool(key and re.search(r'(?:20\d{2}.*(?:q[1-4]|quarter)|(?:q[1-4]|quarter).*20\d{2})', key, re.I))
    return bool(specific and row.get('official_event_key') == key)


def _has_capture_evidence(conn, row: dict) -> bool:
    # Preserve every row that has ever owned a capture; do not merge text or
    # completed calls. This deliberately errs on the side of leaving duplicates.
    if (row.get('status') in {'running', 'completed', 'ended'}
            or row.get('stream_probe_status') == 'probing'
            or row.get('capture_session_id') or int(row.get('capture_attempts') or 0)):
        return True
    result = conn.execute(text('''
        SELECT 1 FROM transcript_segments
        WHERE call_id = :legacy_call_id LIMIT 1
    '''), {'legacy_call_id': str(row['id'])}).first()
    return result is not None


def _calendar_correction_evidence(row: dict, official_day: date, observed: datetime) -> dict | None:
    """Require a recent explicit independent-source correction, not date proximity.

    Yahoo/Nasdaq dates alone must not invent an event identity. Once an issuer
    verifies the fiscal earnings event, the recorded Nasdaq correction can link
    its two untouched calendar buckets across a quarter/year boundary.
    """
    if row.get('schedule_revalidation_reason') != 'date_mismatch':
        return None
    try:
        evidence = json.loads(row.get('schedule_revalidation_evidence') or '{}')
        raw_seen = row.get('schedule_last_nasdaq_seen_at')
        if not isinstance(raw_seen, (str, datetime)) or not raw_seen:
            return None
        seen = _utc_naive(raw_seen)
    except (TypeError, ValueError, KeyError):
        return None
    if not isinstance(evidence, dict) or evidence.get('reason') != 'date_mismatch':
        return None
    old_day = policies._coerce_schedule_date(row.get('earning_at'))
    if (old_day is None or old_day == official_day
            or policies._coerce_schedule_date(evidence.get('database_date')) != old_day
            or policies._coerce_schedule_date(evidence.get('nasdaq_date')) != official_day):
        return None
    if abs((official_day - old_day).days) > 14:
        return None
    if not timedelta(0) <= observed - seen <= timedelta(hours=48):
        return None
    return {**evidence, 'nasdaq_seen_at': str(seen)}


def _unidentified_calendar_row(row: dict, observed: datetime) -> bool:
    """Only a pending calendar guess can become an alias of a proven event."""
    if (row.get('status') != 'upcoming' or row.get('schedule_superseded_by')
            or row.get('capture_lease_owner') or row.get('stream_probe_lease_owner')
            or row.get('verified_fiscal_year') or row.get('verified_fiscal_quarter')
            or row.get('official_event_key') or row.get('official_event_identity')
            or str(row.get('schedule_source') or '').startswith('official')
            or row.get('time_verification_status') == 'verified'):
        return False
    if (row.get('schedule_observed_at')
            and _utc_naive(row['schedule_observed_at']) > observed):
        return False
    # Previously discovered independent event dates/routes are evidence too:
    # leave them intact rather than silently treating them as calendar guesses.
    if row.get('webcast_date') or row.get('event_url') or row.get('webcast_url'):
        return False
    return True


def _reconcile_corroborated_calendar_sibling(
    conn, rows: list[dict], before: dict, canonical: dict,
    identity: dict, observed: datetime,
) -> None:
    """Retire one proven calendar alias in the issuer-observation transaction.

    A full official fiscal identity plus a fresh recorded Nasdaq correction is
    required. More than one plausible sibling is ambiguous and kept watchable.
    Existing official/capture history and newer observations always win.
    """
    official_day = policies._coerce_schedule_date(canonical.get('webcast_date'))
    if (not official_day or not identity.get('fiscal_year')
            or not identity.get('fiscal_quarter')
            or before.get('status') != 'upcoming'
            or before.get('capture_lease_owner') or before.get('stream_probe_lease_owner')
            or _has_capture_evidence(conn, before)):
        return
    canonical_was_calendar = _unidentified_calendar_row(before, observed)
    correction = (_calendar_correction_evidence(before, official_day, observed)
                  if canonical_was_calendar else None)
    candidates = []
    for sibling in rows:
        if sibling['id'] == canonical['id'] or not _unidentified_calendar_row(sibling, observed):
            continue
        # The old row may receive issuer confirmation first, or the new row.
        # In either direction the persisted source mismatch supplies the link.
        proof = _calendar_correction_evidence(sibling, official_day, observed)
        if (proof is None and correction is not None
                and policies._coerce_schedule_date(sibling.get('earning_at')) == official_day):
            proof = correction
        if proof is not None:
            candidates.append((sibling, proof))
    if len(candidates) != 1:
        return
    sibling, proof = candidates[0]
    if _has_capture_evidence(conn, sibling):
        return
    evidence = json.dumps({
        'reason': 'corroborated_official_event',
        'canonical_call_id': canonical['id'],
        'official_event_key': canonical.get('official_event_key'),
        'fiscal_year': identity['fiscal_year'],
        'fiscal_quarter': identity['fiscal_quarter'],
        'official_date': str(official_day),
        'source_correction': proof,
    }, default=str, sort_keys=True)
    after = {**sibling, 'schedule_superseded_by': canonical['id'],
             'schedule_revision': int(sibling.get('schedule_revision') or 0) + 1,
             'schedule_observed_at': observed, 'schedule_revalidation_status': 'superseded',
             'schedule_revalidation_reason': 'corroborated_official_event',
             'schedule_revalidation_evidence': evidence}
    result = conn.execute(text('''
        UPDATE calls SET schedule_superseded_by = :canonical_id,
            schedule_revision = :revision, schedule_observed_at = :observed,
            schedule_revalidation_status = 'superseded',
            schedule_revalidation_reason = 'corroborated_official_event',
            schedule_revalidation_evidence = :evidence
        WHERE id = :call_id AND schedule_revision = :expected_revision
    '''), {'canonical_id': canonical['id'], 'revision': after['schedule_revision'],
           'observed': observed, 'evidence': evidence, 'call_id': sibling['id'],
           'expected_revision': int(sibling.get('schedule_revision') or 0)})
    if result.rowcount != 1:
        return
    _append_history(conn, sibling, after, 'corroborated_calendar_duplicate', observed)


def _apply_official_observation(
    call_id: int, changes: dict, *, reason: str, event_identity: dict | None = None,
    expected_revision: int | None = None, observed_at: datetime | None = None,
    reject_large_shift: bool = True, expected_event_date: date | None = None,
    _connection=None, clock_conflict_route: bool = False,
    clock_observations: list[dict] | None = None,
    clock_source_url: str | None = None,
) -> int | None:
    """Serialize one issuer's observations and reject stale or active-row writes.

    Revision is returned so a discovery and time read from one fetched page can
    be committed in sequence. None means stale, active, conflicting, or duplicate.
    """
    if _connection is None:
        schema.ensure_schedule_time_schema()
    observed = _utc_naive(observed_at)
    identity = _normal_identity(event_identity)
    transaction = connection.engine.begin() if _connection is None else nullcontext(_connection)
    with transaction as conn:
        # Lock in ID order across a ticker to make concurrent duplicate checks
        # deterministic, including observations crossing legacy calendar quarters.
        rows = [dict(row) for row in conn.execute(text('''
            SELECT * FROM calls
            WHERE ticker = (SELECT ticker FROM calls WHERE id = :call_id)
            ORDER BY id FOR UPDATE
        '''), {'call_id': call_id}).mappings()]
        row = next((item for item in rows if int(item['id']) == int(call_id)), None)
        if not row or row.get('status') not in {'upcoming', 'live'}:
            return None
        if row.get('stream_probe_status') == 'probing' or row.get('schedule_superseded_by'):
            return None
        if _connection is None:
            # capture_session_id is durable history after a failed/released
            # capture, not an active lease. Blocking on it would permanently
            # freeze this row's clock and route after its first failed attempt.
            lease_until = row.get('capture_lease_until')
            if ((lease_until and _utc_naive(lease_until) > datetime.utcnow())
                    or (row.get('capture_lease_owner') and not lease_until)):
                return None
        revision = int(row.get('schedule_revision') or 0)
        if expected_revision is not None and revision != int(expected_revision):
            return None
        if row.get('schedule_observed_at') and observed < _utc_naive(row['schedule_observed_at']):
            return None
        for key, field in [('fiscal_year', 'verified_fiscal_year'),
                           ('fiscal_quarter', 'verified_fiscal_quarter')]:
            if identity.get(key) and row.get(field) and str(identity[key]) != str(row[field]):
                return None
        old_date = policies._coerce_schedule_date(row.get('webcast_date') or row.get('earning_at'))
        if expected_event_date is not None and old_date != expected_event_date:
            return None
        new_date = policies._coerce_schedule_date(changes.get('webcast_date'))
        if (reject_large_shift and old_date and new_date
                and abs((new_date - old_date).days) > policies._nonnegative_env_int('OFFICIAL_EVENT_DATE_GRACE_DAYS', 2)
                and not (identity and identity.get('date_shift_verified') is True)):
            return None
        # A fresh route and an uncertain clock are independent observations,
        # but only exact same-day, authenticated event routes may be separated.
        if clock_conflict_route and (reason != 'ambiguous_call_time' or old_date != new_date
                or not identity or not authenticated_route({**row, **changes})):
            return None
        redirected = False
        if identity:
            duplicates = [item for item in rows if item['id'] != row['id']
                          and not item.get('schedule_superseded_by')
                          and _same_official_event(item, identity)]
            # Once an identity is established, later broad-calendar duplicates
            # point to that canonical row. No dates alone justify suppression.
            if duplicates and not _has_capture_evidence(conn, row):
                canonical = min(duplicates, key=lambda item: item['id'])
                if not _has_capture_evidence(conn, canonical):
                    after = {**row, 'schedule_superseded_by': canonical['id'],
                             'schedule_revision': revision + 1, 'schedule_observed_at': observed,
                             'schedule_revalidation_status': 'superseded',
                             'schedule_revalidation_reason': 'same_official_event'}
                    conn.execute(text('''
                        UPDATE calls SET schedule_superseded_by = :canonical_id,
                            schedule_revision = :revision, schedule_observed_at = :observed,
                            schedule_revalidation_status = 'superseded',
                            schedule_revalidation_reason = 'same_official_event'
                        WHERE id = :call_id
                    '''), {'canonical_id': canonical['id'], 'revision': revision + 1,
                           'observed': observed, 'call_id': call_id})
                    _append_history(conn, row, after, 'duplicate_official_event', observed)
                    if canonical.get('schedule_observed_at') and observed < _utc_naive(canonical['schedule_observed_at']):
                        return None
                    canonical_day = policies._coerce_schedule_date(canonical.get('webcast_date') or canonical.get('earning_at'))
                    if (new_date and canonical_day and abs((new_date - canonical_day).days) > policies._nonnegative_env_int('OFFICIAL_EVENT_DATE_GRACE_DAYS', 2)
                            and not identity.get('date_shift_verified')):
                        return None
                    # Apply the fresh observation to the already established
                    # identity in this transaction; do not wait another cycle.
                    row = canonical
                    call_id = canonical['id']
                    revision = int(canonical.get('schedule_revision') or 0)
                    old_date = canonical_day
                    redirected = True
            changes = dict(changes)
            changes.update({
                'verified_fiscal_year': identity.get('fiscal_year') or row.get('verified_fiscal_year'),
                'verified_fiscal_quarter': identity.get('fiscal_quarter') or row.get('verified_fiscal_quarter'),
                'official_event_key': identity.get('official_event_key') or row.get('official_event_key'),
                'official_event_identity': json.dumps(identity, default=str, sort_keys=True),
            })
        if reason == 'official_discovery' and new_date and new_date != old_date:
            changes = dict(changes)
            changes.update(scheduled_at_utc=None, source_timezone=None,
                           time_verification_status='unverified', time_verified_at=None)
        # Route or date-only observations cannot resolve a clock contradiction.
        # Keep the durable sides while allowing independently valid route work.
        from ..collectors.schedules.clock_reconciliation import read_clock_evidence
        previous_clock_evidence = read_clock_evidence(row)
        same_event = not (new_date and new_date != old_date and identity
                          and identity.get('date_shift_verified'))
        if (same_event and reason in {'official_discovery', 'official_date_without_time'}
                and (row.get('schedule_revalidation_reason') == 'ambiguous_call_time'
                     or previous_clock_evidence.get('clock_state') == 'conflicted')):
            changes = {**changes, 'scheduled_at_utc': None, 'source_timezone': None,
                'time_verified_at': None, 'time_verification_status': 'unverified',
                'schedule_revalidation_status': 'provisional_watch',
                'schedule_revalidation_reason': 'ambiguous_call_time',
                'schedule_revalidation_evidence': row.get('schedule_revalidation_evidence')}
        elif not same_event and reason in {'official_discovery', 'official_date_without_time'}:
            changes = {**changes, 'schedule_revalidation_evidence': None}
        clock_conflicted = False
        if reason in {'official_time', 'ambiguous_call_time'}:
            clocks = clock_observations
            if clocks is None and reason == 'ambiguous_call_time':
                try:
                    details = json.loads(changes.get('schedule_revalidation_evidence') or '{}')
                    clocks = details.get('clock_observations') if isinstance(details, dict) else None
                except (ValueError, TypeError):
                    clocks = None
            if not clocks and reason == 'official_time':
                source = clock_source_url or (
                    (changes.get('webcast_url') or row.get('webcast_url'))
                    if 'provider' in str(changes.get('schedule_source') or '')
                    else (changes.get('event_url') or row.get('event_url')))
                clocks = [{'source': source, 'value': changes.get('scheduled_at_utc'),
                           'source_timezone': changes.get('source_timezone'),
                           'evidence': changes.get('schedule_evidence'), 'observed_at': observed}]
            if clocks:
                clock_result = reconcile_clock_observations(row, clocks, observed_at=observed,
                    reset_event=bool(new_date and new_date != old_date and identity
                                     and identity.get('date_shift_verified')),
                    freshness_seconds=policies._env_int('SCHEDULE_TIME_LIVE_MAX_AGE_MINUTES', 120) * 60)
                if (reason == 'official_time' and clock_observations is not None
                        and not clock_result['has_current_clock']):
                    return None
                clock_conflicted = clock_result['conflicted'] or reason == 'ambiguous_call_time'
                clock_details = clock_result['evidence']
                if clock_conflicted:
                    clock_details['clock_state'] = 'conflicted'
                    clock_details.setdefault('clock_conflict_started_at', observed.replace(tzinfo=timezone.utc).isoformat())
                    clock_details.setdefault('required_clock_sources', [item['source'] for item in clock_details['clock_observations']])
                    # No adapter, including a leased browser probe, may erase
                    # another source's unresolved clock with a single reading.
                    reason = 'ambiguous_call_time'
                    changes = {**changes, 'scheduled_at_utc': None, 'source_timezone': None,
                        'time_verified_at': None, 'time_verification_status': 'unverified',
                        'schedule_revalidation_status': 'provisional_watch',
                        'schedule_revalidation_reason': 'ambiguous_call_time',
                        'schedule_enrichment_failure_kind': 'ambiguous_call_time',
                        'schedule_enrichment_last_error': 'Schedule clocks disagree or a conflicting source has not been re-observed',
                        'schedule_enrichment_retry_not_before': observed + timedelta(
                            minutes=policies._env_int('SCHEDULE_TIME_NEAR_REVERIFY_MINUTES', 10))}
                    clock_conflict_route = bool(new_date == old_date and authenticated_route({**row, **changes}))
                changes = {**changes, 'schedule_revalidation_evidence': json.dumps(clock_details, sort_keys=True)}
        route_retained = False
        if reason in {'official_time', 'official_discovery'}:
            retained = retained_route_fields(row, changes, identity)
            if retained:
                changes = {**changes, **retained}
                route_retained = True
        if reason == 'ambiguous_call_time':
            # This reason now means only clock disagreement. Legacy ambiguity
            # has no marker and cannot bypass identity/TTL checks in the worker.
            if not clock_conflict_route:
                retained = retained_route_fields(row, {**changes,
                    'webcast_date': changes.get('webcast_date') or old_date}, identity)
                if retained:
                    changes = {**changes, **retained}
                route_retained = bool(authenticated_route({**row, **changes}))
            try:
                clock_details = json.loads(changes.get('schedule_revalidation_evidence') or '{}')
            except (ValueError, TypeError):
                clock_details = {}
            if not isinstance(clock_details, dict):
                clock_details = {}
            observations = clock_details.get('clock_observations')
            diagnostics = {key: clock_details[key] for key in (
                'clock_validation_version', 'clock_state', 'clock_conflict_started_at',
                'required_clock_sources', 'missing_clock_sources', 'clock_sources_incomplete') if key in clock_details}
            if isinstance(observations, list):
                diagnostics['clock_observations'] = observations[:12]
            if clock_conflict_route or route_retained:
                changes = {**changes, 'schedule_revalidation_evidence': json.dumps({
                    **diagnostics,
                    'conflict_kind': 'start_time_conflict', 'route_identity_verified': True,
                    'route_action': 'observed' if clock_conflict_route else 'retained'}, sort_keys=True)}
            else:
                changes = {**changes, 'schedule_discovery_fingerprint': None,
                           'schedule_discovery_checked_at': None,
                           'schedule_revalidation_evidence': json.dumps(diagnostics, sort_keys=True) if diagnostics else None}
        # Compare typed SQL dates/times and SQLite fixture strings consistently.
        def comparable(value):
            if isinstance(value, (date, datetime)):
                return str(value)
            return value
        material_fields = {'webcast_date', 'scheduled_at_utc', 'source_timezone',
                           'event_url', 'webcast_url', 'time_verification_status',
                           'verified_fiscal_year', 'verified_fiscal_quarter', 'official_event_key',
                           'schedule_revalidation_status', 'schedule_revalidation_reason',
                           'schedule_discovery_fingerprint'}
        changed = any(comparable(row.get(key)) != comparable(value)
                      for key, value in changes.items() if key in material_fields)
        after = {**row, **changes, 'schedule_revision': revision + int(changed),
                 'schedule_observed_at': observed}
        if changed:
            after.update({
                'video_url': None, 'stream_probe_status': 'pending',
                'stream_probe_attempts': 0, 'last_stream_probe_at': None,
                'last_stream_probe_error': None, 'stream_probe_retry_not_before': None,
                'stream_probe_retry_reason': None, 'stream_detected_at': None,
                'capture_retry_not_before': None, 'capture_last_error': None,
                'schedule_discovery_changed_at': observed,
            })
        same_discovery_observation = (
            reason == 'official_time' and row.get('schedule_discovery_checked_at')
            and _utc_naive(row['schedule_discovery_checked_at']) == observed
            and changes.get('event_url') == row.get('event_url')
            and changes.get('webcast_url') == row.get('webcast_url'))
        fresh_supplied_route = ((reason == 'official_time' or clock_conflict_route)
                                and bool(changes.get('schedule_discovery_fingerprint')))
        if reason != 'official_discovery' and changed and not same_discovery_observation and not fresh_supplied_route and not route_retained:
            after['schedule_discovery_fingerprint'] = None
            after['schedule_discovery_checked_at'] = None
        updates = {key: value for key, value in after.items() if key != 'id' and
                   (key in changes or comparable(row.get(key)) != comparable(value))}
        # Metadata contains only columns constructed internally, never page text.
        assignment = ', '.join(f'{key} = :{key}' for key in updates)
        conn.execute(text(f'UPDATE calls SET {assignment} WHERE id = :call_id'),
                     {**updates, 'call_id': call_id})
        # A clock freshness heartbeat belongs in time_verified_at, not a new
        # history row. Keep material/evidence changes append-only.
        def audit_evidence(value):
            try:
                parsed = json.loads(value) if isinstance(value, str) else value
                if isinstance(parsed, dict) and parsed.get('clock_validation_version'):
                    parsed = dict(parsed)
                    parsed['clock_observations'] = [{k: v for k, v in item.items()
                        if k != 'observed_at'} if isinstance(item, dict) else item
                        for item in parsed.get('clock_observations', [])]
                    return parsed
            except (TypeError, ValueError):
                pass
            return value
        audit_changed = any(row.get(key) != after.get(key) for key in (
            'schedule_source', 'schedule_evidence', 'official_event_identity',
            'schedule_revalidation_reason')) or (audit_evidence(row.get('schedule_revalidation_evidence'))
                != audit_evidence(after.get('schedule_revalidation_evidence')))

        if changed or audit_changed:
            _append_history(conn, row, after, reason, observed)
        if identity:
            _reconcile_corroborated_calendar_sibling(conn, rows, row, after, identity, observed)
        return None if redirected or clock_conflicted else after['schedule_revision']


def update_verified_schedule_time(
    call_id: int, evidence: Dict[str, Any], *, _connection=None,
) -> int | None:
    """Persist current issuer evidence, with schedule_revalidation_status = 'clear'."""
    evidence = dict(evidence)
    if stored_event_kind_conflict(evidence.get('schedule_evidence')):
        return None
    identity = evidence.pop('event_identity', None)
    expected_revision = evidence.pop('expected_revision', None)
    observed_at = evidence.pop('observed_at', None)
    clock_observations = evidence.pop('clock_observations', None)
    clock_source_url = evidence.pop('clock_source_url', None)
    route_observed_at = evidence.pop('route_observed_at', None)
    now = _utc_naive(observed_at)
    allowed = {'webcast_date', 'scheduled_at_utc', 'source_timezone', 'event_url',
               'webcast_url', 'schedule_source', 'schedule_evidence', 'schedule_discovery_fingerprint'}
    changes = {key: value for key, value in evidence.items() if key in allowed}
    fingerprint = str(changes.get('schedule_discovery_fingerprint') or '')
    if re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        try:
            route_time = _utc_naive(route_observed_at) if route_observed_at is not None else now
        except (TypeError, ValueError):
            return None
        if route_time > now:
            return None
        changes['schedule_discovery_checked_at'] = route_time
    else:
        changes.pop('schedule_discovery_fingerprint', None)
    for key in ('event_url', 'webcast_url'):
        value = changes.get(key)
        if value is None:
            continue
        # Redaction is not URL validation: it stringifies arbitrary values.
        # Reject the entire observation before DB work if a typed clock or
        # malformed/credential-bearing address is placed in a route field.
        if (not isinstance(value, str) or not value or value != value.strip()
                or any(character.isspace() or ord(character) < 32 for character in value)):
            return None
        try:
            from urllib.parse import urlsplit
            route = urlsplit(value)
            if (route.scheme not in {'http', 'https'} or not route.hostname
                    or route.username or route.password or '\\' in value
                    or route.port == 0):
                return None
        except ValueError:
            return None
        changes[key] = redaction.redact_sensitive_url(value)
    changes.update(time_verification_status='verified', time_verified_at=now,
                   schedule_revalidation_status='clear', schedule_revalidation_reason=None,
                   schedule_revalidation_evidence=None, schedule_enrichment_last_attempt_at=now,
                   schedule_enrichment_retry_not_before=None, schedule_enrichment_failure_kind=None,
                   schedule_enrichment_last_error=None)
    return _apply_official_observation(call_id, changes, reason='official_time',
                                      event_identity=identity, expected_revision=expected_revision,
                                      observed_at=now, _connection=_connection,
                                      clock_observations=clock_observations, clock_source_url=clock_source_url)


def confirm_schedule_revalidation_from_official_ir(
    call_id: int, *, event_url: str, evidence: str, webcast_date: date | None = None,
    event_identity: dict | None = None, expected_revision: int | None = None,
    observed_at: datetime | None = None,
) -> int | None:
    """Official page confirms a day but no usable time: keep the date watchable.

    schedule_revalidation_status = 'clear' permits the watcher; stale exact time
    is explicitly withdrawn only on a successful issuer-page observation.
    """
    changes = {'event_url': redaction.redact_sensitive_url(event_url),
               'schedule_source': 'official_ir_date',
               'schedule_evidence': redaction.redact_sensitive_text(evidence)[:2000],
               'scheduled_at_utc': None, 'source_timezone': None, 'time_verified_at': None,
               'time_verification_status': 'unverified',
               'schedule_revalidation_status': 'clear', 'schedule_revalidation_reason': None,
               'schedule_revalidation_evidence': redaction.redact_sensitive_text(evidence)[:2000]}
    if webcast_date:
        changes['webcast_date'] = webcast_date
    return _apply_official_observation(call_id, changes, reason='official_date_without_time',
                                      event_identity=event_identity, expected_revision=expected_revision,
                                      observed_at=observed_at)


def update_official_schedule_discovery(
    call_id: int, *, webcast_date: date | None, event_url: str | None,
    webcast_url: str | None, source: str, evidence: str, fingerprint: str,
    event_identity: dict | None = None, expected_revision: int | None = None,
    observed_at: datetime | None = None,
) -> int | None:
    """Persist current issuer-linked route and invalidate stale date/time state."""
    # Route discovery is not proof that an old clock time is still valid. The
    # same fetch's verified time, if present, follows with the returned revision.
    changes = {'event_url': redaction.redact_sensitive_url(event_url) if event_url else None,
               'webcast_url': redaction.redact_sensitive_url(webcast_url) if webcast_url else None,
               'schedule_source': str(source)[:64],
               'schedule_evidence': redaction.redact_sensitive_text(evidence)[:2000],
               'schedule_discovery_fingerprint': str(fingerprint)[:64],
               'schedule_discovery_checked_at': _utc_naive(observed_at),
               'schedule_enrichment_last_attempt_at': _utc_naive(observed_at),
               'schedule_enrichment_retry_not_before': None,
               'schedule_enrichment_failure_kind': None, 'schedule_enrichment_last_error': None}
    if webcast_date:
        changes.update(webcast_date=webcast_date, schedule_revalidation_status='clear',
                       schedule_revalidation_reason=None)
    return _apply_official_observation(call_id, changes, reason='official_discovery',
                                      event_identity=event_identity, expected_revision=expected_revision,
                                      observed_at=observed_at)


def quarantine_schedule_for_official_page_date_mismatch(
    call_id: int, *, expected_date: object, observed_date: date, error: str | None,
) -> bool:
    """Unproven large shifts request issuer revalidation; do not rewrite identity."""
    stored_date = policies._coerce_schedule_date(expected_date)
    if stored_date is None or observed_date == stored_date:
        return False
    nearby = abs((observed_date - stored_date).days) <= policies._nonnegative_env_int(
        'OFFICIAL_EVENT_DATE_GRACE_DAYS', 2)
    reason = ('official_call_date_differs_from_release_date' if nearby
              else 'official_page_date_mismatch')
    evidence = json.dumps({'reason': reason, 'database_date': stored_date.isoformat(),
                           'official_page_date': observed_date.isoformat(),
                           'probe_error': redaction.redact_sensitive_text(error or '')[:1000]}, sort_keys=True)
    values = {'scheduled_at_utc': None, 'source_timezone': None,
              'time_verification_status': 'unverified', 'time_verified_at': None,
              'schedule_revalidation_status': 'clear' if nearby else 'required',
              'schedule_revalidation_reason': None if nearby else reason,
              'schedule_revalidation_evidence': evidence,
              'schedule_enrichment_last_attempt_at': None,
              'schedule_enrichment_retry_not_before': None,
              'schedule_enrichment_failure_kind': None, 'schedule_enrichment_last_error': None}
    if nearby:
        values.update(webcast_date=observed_date, schedule_source='official_provider_date',
                      schedule_evidence=evidence)
    # A browser observation may finish after a newer issuer refresh. Compare its
    # expected day under the same transaction before acting on mismatch evidence.
    result = _apply_official_observation(call_id, values, reason=reason,
                                        expected_event_date=stored_date)
    return not nearby and result is not None


def invalidate_non_earnings_schedule_evidence(*, reference_time_utc=None, days_ahead=14, limit=200):
    """Withdraw contradictory legacy evidence during the regular time refresh.

    No network lookup or issuer exception is needed. Completed/captured/leased
    records are preserved. The locked row is rechecked against the snapshot
    revision and evidence before a bounded compare-and-swap update with history.
    Access cooldowns survive; only a wait derived from the withdrawn clock ends.
    """
    now = _utc_naive(reference_time_utc)
    day = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(
        os.getenv('DATE_STREAM_WATCH_TIMEZONE', 'America/New_York'))).date()
    with connection.engine.connect() as conn:
        candidates = [dict(r) for r in conn.execute(text("""
            SELECT * FROM calls WHERE status = 'upcoming'
              AND schedule_superseded_by IS NULL
              AND COALESCE(stream_probe_status, 'pending') <> 'probing'
              AND schedule_source LIKE 'official%'
              AND schedule_evidence IS NOT NULL
              AND COALESCE(webcast_date, DATE(earning_at)) >= :start_day
              AND COALESCE(webcast_date, DATE(earning_at)) < :end_day
            ORDER BY COALESCE(webcast_date, DATE(earning_at)), id LIMIT :limit
        """), {'start_day': day - timedelta(days=2),
               'end_day': day + timedelta(days=max(1, int(days_ahead))),
               'limit': max(1, int(limit))}).mappings()]
    invalidated = 0
    for snapshot in candidates:
        if not stored_event_kind_conflict(snapshot.get('schedule_evidence')):
            continue
        with connection.engine.begin() as conn:
            # Same issuer lock order as normal verified-time observations.
            rows = [dict(r) for r in conn.execute(text("""
                SELECT * FROM calls WHERE ticker = :ticker ORDER BY id FOR UPDATE
            """), {'ticker': snapshot['ticker']}).mappings()]
            row = next((r for r in rows if r['id'] == snapshot['id']), None)
            if (not row or row.get('status') != 'upcoming' or row.get('schedule_superseded_by')
                    or row.get('capture_lease_owner') or row.get('stream_probe_lease_owner')
                    or row.get('capture_lease_until') or row.get('stream_probe_lease_until')
                    or _has_capture_evidence(conn, row)
                    or int(row.get('schedule_revision') or 0) != int(snapshot.get('schedule_revision') or 0)
                    or row.get('schedule_evidence') != snapshot.get('schedule_evidence')
                    or (row.get('schedule_observed_at') and _utc_naive(row['schedule_observed_at']) > now)):
                continue
            changes = dict(webcast_date=None, scheduled_at_utc=None, source_timezone=None,
                event_url=None, webcast_url=None, video_url=None, schedule_source=None,
                schedule_evidence=None, time_verified_at=None, time_verification_status='unverified',
                verified_fiscal_year=None, verified_fiscal_quarter=None, official_event_key=None,
                official_event_identity=None, schedule_discovery_fingerprint=None,
                schedule_discovery_checked_at=None, schedule_discovery_changed_at=now,
                schedule_revalidation_status='provisional_watch',
                schedule_revalidation_reason='stored_non_earnings_event',
                schedule_revalidation_evidence=json.dumps({'reason':'stored_non_earnings_event',
                    'previous_revision':int(row.get('schedule_revision') or 0)}),
                schedule_revision=int(row.get('schedule_revision') or 0) + 1, schedule_observed_at=now)
            if row.get('stream_probe_retry_reason') == 'scheduled_start_wait':
                changes.update(stream_probe_retry_not_before=None, stream_probe_retry_reason=None)
            assignment = ', '.join(f'{field} = :{field}' for field in changes)
            result = conn.execute(text(f"""UPDATE calls SET {assignment}
                WHERE id = :call_id AND schedule_revision = :expected_revision
                  AND status = 'upcoming' AND schedule_superseded_by IS NULL
                  AND COALESCE(stream_probe_status, 'pending') <> 'probing'
            """), {**changes, 'call_id':row['id'], 'expected_revision':int(row.get('schedule_revision') or 0)})
            if result.rowcount == 1:
                _append_history(conn, row, {**row, **changes}, 'stored_non_earnings_event', now)
                invalidated += 1
    return invalidated
