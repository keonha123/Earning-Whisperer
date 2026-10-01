"""Transcript archive and durable delivery outbox."""

from sqlalchemy import text
import hashlib
import json
from typing import Any, Dict, List
from . import connection, redaction, schema


def archive_transcript_segment(
    payload: Dict[str, Any],
    *,
    ensure_schema: bool = True,
) -> None:
    """Persist one STT segment without storing the source audio."""
    if ensure_schema:
        schema.ensure_transcript_archive_schema()
    query = text("""
        INSERT INTO transcript_segments (
            call_id, ticker, sequence_no, start_ms, end_ms, text_chunk,
            speaker, source_timestamp, is_session_end, session_end_reason,
            session_success_eligible, target_identity_verified
        ) VALUES (
            :call_id, :ticker, :sequence_no, :start_ms, :end_ms, :text_chunk,
            :speaker, :source_timestamp, :is_session_end, :session_end_reason,
            :session_success_eligible, :target_identity_verified
        )
        ON DUPLICATE KEY UPDATE
            ticker = VALUES(ticker),
            start_ms = VALUES(start_ms),
            end_ms = VALUES(end_ms),
            text_chunk = VALUES(text_chunk),
            speaker = VALUES(speaker),
            source_timestamp = VALUES(source_timestamp),
            is_session_end = GREATEST(is_session_end, VALUES(is_session_end)),
            session_end_reason = COALESCE(
                VALUES(session_end_reason), session_end_reason
            ),
            session_success_eligible = GREATEST(
                session_success_eligible, VALUES(session_success_eligible)
            ),
            target_identity_verified = GREATEST(
                target_identity_verified, VALUES(target_identity_verified)
            )
    """)
    params = {
        "call_id": str(payload.get("call_id") or "")[:128],
        "ticker": str(payload.get("ticker") or "").upper()[:20],
        "sequence_no": int(payload.get("sequence") or 0),
        "start_ms": max(0, int(payload.get("start_ms") or 0)),
        "end_ms": max(0, int(payload.get("end_ms") or 0)),
        "text_chunk": str(payload.get("text") or ""),
        "speaker": payload.get("speaker"),
        "source_timestamp": payload.get("timestamp"),
        "is_session_end": bool(payload.get("is_session_end")),
        "session_end_reason": str(payload.get("session_end_reason") or "")[:64] or None,
        "session_success_eligible": bool(payload.get("session_success_eligible")),
        "target_identity_verified": bool(payload.get("target_identity_verified")),
    }
    if not params["call_id"] or not params["ticker"] or not params["text_chunk"]:
        return
    with connection.engine.begin() as conn:
        conn.execute(query, params)


def mark_transcript_session_end(
    call_id: str,
    sequence_no: int,
    *,
    termination_reason: str = "legacy_terminal_marker",
    success_eligible: bool = False,
    target_identity_verified: bool = False,
    ensure_schema: bool = True,
) -> bool:
    """Mark the latest real transcript row with a classified session outcome."""
    if ensure_schema:
        schema.ensure_transcript_archive_schema()
    query = text("""
        UPDATE transcript_segments
        SET is_session_end = TRUE,
            session_end_reason = CASE
                WHEN session_success_eligible = TRUE AND :success_eligible = FALSE
                THEN session_end_reason
                ELSE :termination_reason
            END,
            session_success_eligible = GREATEST(
                session_success_eligible, :success_eligible
            ),
            target_identity_verified = GREATEST(
                target_identity_verified, :target_identity_verified
            )
        WHERE call_id = :call_id
          AND sequence_no = :sequence_no
    """)
    with connection.engine.begin() as conn:
        result = conn.execute(
            query,
            {
                "call_id": str(call_id)[:128],
                "sequence_no": max(0, int(sequence_no)),
                "termination_reason": str(termination_reason or "unknown")[:64],
                "success_eligible": bool(success_eligible),
                "target_identity_verified": bool(target_identity_verified),
            },
        )
        return result.rowcount == 1


def enqueue_transcript_delivery(
    payload: Dict[str, Any],
    destination: str,
    *,
    ensure_schema: bool = True,
) -> None:
    """Persist one idempotent transcript delivery before attempting HTTP."""
    if ensure_schema:
        schema.ensure_transcript_outbox_schema()
    import json

    destination_value = str(destination).strip().lower()
    if destination_value not in {"ai_engine", "backend"}:
        raise ValueError(f"unsupported transcript destination: {destination}")
    call_id = str(payload.get("call_id") or "")[:128]
    ticker = str(payload.get("ticker") or "").upper()[:20]
    sequence = int(payload.get("sequence") or 0)
    if not call_id or not ticker:
        return
    delivery_key = hashlib.sha256(
        f"{call_id}|{destination_value}|{sequence}".encode("utf-8")
    ).hexdigest()
    query = text("""
        INSERT INTO transcript_outbox (
            delivery_key, call_id, ticker, sequence_no, destination, payload_json
        ) VALUES (
            :delivery_key, :call_id, :ticker, :sequence_no, :destination, :payload_json
        )
        ON DUPLICATE KEY UPDATE
            payload_json = VALUES(payload_json),
            updated_at = CURRENT_TIMESTAMP
    """)
    with connection.engine.begin() as conn:
        conn.execute(
            query,
            {
                "delivery_key": delivery_key,
                "call_id": call_id,
                "ticker": ticker,
                "sequence_no": sequence,
                "destination": destination_value,
                "payload_json": json.dumps(payload, ensure_ascii=True, default=str),
            },
        )


def get_pending_transcript_deliveries(limit: int = 50) -> List[Dict[str, Any]]:
    """Return due outbox rows for a bounded retry worker."""
    schema.ensure_transcript_outbox_schema()
    query = text("""
        SELECT id, delivery_key, call_id, ticker, sequence_no, destination,
               payload_json, status, attempt_count, next_attempt_at, last_error
        FROM transcript_outbox
        WHERE status IN ('pending', 'failed')
          AND next_attempt_at <= UTC_TIMESTAMP()
        ORDER BY id ASC
        LIMIT :limit
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, {"limit": max(1, int(limit))})]


def mark_transcript_delivery_result(
    outbox_id: int,
    *,
    success: bool,
    error: str | None = None,
    retry_delay_seconds: int = 30,
) -> None:
    """Advance an outbox item with bounded exponential retry timing."""
    schema.ensure_transcript_outbox_schema()
    delay = max(1, min(86400, int(retry_delay_seconds)))
    if success:
        query = text("""
            UPDATE transcript_outbox
            SET status = 'sent', sent_at = UTC_TIMESTAMP(),
                attempt_count = attempt_count + 1, last_error = NULL
            WHERE id = :id
        """)
        params = {"id": outbox_id}
    else:
        query = text(
            "UPDATE transcript_outbox "
            "SET status = 'failed', attempt_count = attempt_count + 1, "
            "last_error = :error, "
            f"next_attempt_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL {delay} SECOND) "
            "WHERE id = :id"
        )
        params = {"id": outbox_id, "error": redaction.redact_sensitive_text(str(error or ""))[:1000]}
    with connection.engine.begin() as conn:
        conn.execute(query, params)


def purge_transcript_segments(
    retention_days: int = 180,
    *,
    batch_size: int = 10000,
    max_batches: int = 10,
) -> int:
    """Delete old transcript rows in bounded batches to avoid a long table lock."""
    schema.ensure_transcript_archive_schema()
    days = max(1, int(retention_days))
    batch = max(100, int(batch_size))
    batches = max(1, int(max_batches))
    deleted = 0

    # The values are validated integers above before being embedded in the MySQL
    # interval/limit clauses, which do not accept bound parameters consistently.
    query = text(
        "DELETE FROM transcript_segments "
        f"WHERE created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL {days} DAY) "
        f"LIMIT {batch}"
    )
    for _ in range(batches):
        with connection.engine.begin() as conn:
            result = conn.execute(query)
            removed = int(result.rowcount or 0)
        deleted += removed
        if removed < batch:
            break
    return deleted


def get_archived_transcript_segments(call_id: str) -> List[Dict[str, Any]]:
    """Read one call's archived transcript in sequence order."""
    schema.ensure_transcript_archive_schema()
    query = text("""
        SELECT call_id, ticker, sequence_no, start_ms, end_ms, text_chunk,
               speaker, source_timestamp, is_session_end, session_end_reason,
               session_success_eligible, target_identity_verified, created_at
        FROM transcript_segments
        WHERE call_id = :call_id
        ORDER BY sequence_no ASC
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, {"call_id": call_id})]


def get_transcript_session_summary(call_id: str) -> Dict[str, Any]:
    """Return durable STT proof for one capture session ID."""
    schema.ensure_transcript_archive_schema()
    query = text("""
        SELECT COUNT(*) AS segment_count,
               COALESCE(SUM(is_session_end = TRUE), 0) AS session_end_count,
               COALESCE(SUM(
                   is_session_end = TRUE AND session_success_eligible = TRUE
               ), 0) AS successful_end_count,
               COALESCE(SUM(
                   is_session_end = TRUE AND target_identity_verified = TRUE
               ), 0) AS identity_verified_end_count,
               COALESCE(SUM(
                   is_session_end = TRUE
                   AND session_success_eligible = TRUE
                   AND target_identity_verified = TRUE
               ), 0) AS valid_end_count,
               MAX(CASE WHEN is_session_end = TRUE THEN session_end_reason END)
                   AS session_end_reason
        FROM transcript_segments
        WHERE call_id = :call_id
    """)
    with connection.engine.connect() as conn:
        row = conn.execute(query, {"call_id": str(call_id)[:128]}).mappings().one()
    return {
        "segment_count": int(row.get("segment_count") or 0),
        "session_end_count": int(row.get("session_end_count") or 0),
        "successful_end_count": int(row.get("successful_end_count") or 0),
        "identity_verified_end_count": int(
            row.get("identity_verified_end_count") or 0
        ),
        "valid_end_count": int(row.get("valid_end_count") or 0),
        "session_end_reason": row.get("session_end_reason"),
    }
