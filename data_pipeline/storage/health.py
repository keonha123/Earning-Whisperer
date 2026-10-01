"""Read-only operational health counters."""

from sqlalchemy import text
from typing import Any, Dict
from . import connection, policies, schema
from ..live_telemetry import archive_spool_health


def get_operational_health_snapshot(stale_minutes: int | None = None) -> Dict[str, Any]:
    """Return bounded DB counters used by the operational alert loop."""
    schema.ensure_schedule_time_schema()
    schema.ensure_transcript_outbox_schema()
    stale = max(
        1,
        int(stale_minutes)
        if stale_minutes is not None
        else policies._env_int("DATE_STREAM_STALE_LEASE_MINUTES", 20),
    )
    query = text(f"""
        SELECT
            (
                SELECT COUNT(*) FROM calls
                WHERE stream_probe_status = 'probing'
                  AND (
                      stream_probe_lease_until IS NULL
                      OR stream_probe_lease_until <= UTC_TIMESTAMP()
                      OR stream_probe_heartbeat_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL {stale} MINUTE)
                  )
            ) AS stale_probe_count,
            (
                SELECT COUNT(*) FROM calls
                WHERE status = 'running'
                  AND (
                      capture_lease_until IS NULL
                      OR capture_lease_until <= UTC_TIMESTAMP()
                      OR capture_heartbeat_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL {stale} MINUTE)
                  )
            ) AS stale_capture_count,
            (
                SELECT COUNT(*) FROM transcript_outbox
                WHERE status IN ('pending', 'failed')
                  AND next_attempt_at <= UTC_TIMESTAMP()
            ) AS due_outbox_count,
            (
                SELECT COUNT(*) FROM transcript_outbox
                WHERE status IN ('pending', 'failed')
            ) AS total_outbox_count,
            (
                SELECT COUNT(*) FROM transcript_outbox
                WHERE status = 'failed'
            ) AS failed_outbox_count
    """)
    with connection.engine.connect() as conn:
        row = conn.execute(query).mappings().one()
        # Session-bound text is the progress signal. A heartbeat, an old event's
        # rows, or successful browser navigation cannot satisfy this query.
        calls = [dict(item) for item in conn.execute(text("""
            SELECT c.id, c.ticker, c.status, c.schedule_revision,
                   c.scheduled_at_utc, c.capture_started_at, c.capture_session_id,
                   c.last_stream_probe_at, c.last_stream_probe_error,
                   (SELECT MAX(t.created_at) FROM transcript_segments t
                    WHERE t.call_id = c.capture_session_id) AS last_text_at
            FROM calls c
            WHERE c.schedule_superseded_by IS NULL
              AND c.status IN ('upcoming', 'live', 'running')
              AND (c.status = 'running' OR c.scheduled_at_utc BETWEEN
                   DATE_SUB(UTC_TIMESTAMP(), INTERVAL 3 HOUR) AND
                   DATE_ADD(UTC_TIMESTAMP(), INTERVAL 20 MINUTE)
                   OR (c.scheduled_at_utc IS NULL AND c.last_stream_probe_at >=
                       DATE_SUB(UTC_TIMESTAMP(), INTERVAL 20 MINUTE)))
            ORDER BY c.scheduled_at_utc, c.id LIMIT 100
        """)).mappings()]
    return {**{key: int(value or 0) for key, value in row.items()},
            **archive_spool_health(), 'live_calls': calls}
