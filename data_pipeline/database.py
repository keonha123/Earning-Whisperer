# database.py
from sqlalchemy import create_engine, text
import hashlib
import os
from datetime import datetime, timedelta
from dotenv import dotenv_values
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

DATA_PIPELINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DATA_PIPELINE_ROOT.parent

def _load_env_defaults() -> None:
    """Load checked-in defaults without overriding Docker or shell environment values."""
    values = {
        **dotenv_values(REPO_ROOT / ".env"),
        **dotenv_values(DATA_PIPELINE_ROOT / ".env"),
    }
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)


_load_env_defaults()
DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:password@localhost:3306/graduate_project")
engine = create_engine(DB_URL)


SCHEDULE_TIME_COLUMNS = {
    "scheduled_at_utc": "DATETIME NULL",
    "source_timezone": "VARCHAR(64) NULL",
    "event_url": "VARCHAR(2048) NULL",
    "webcast_url": "VARCHAR(2048) NULL",
    "schedule_source": "VARCHAR(64) NULL",
    "schedule_evidence": "TEXT NULL",
    "time_verification_status": "VARCHAR(32) NOT NULL DEFAULT 'unverified'",
    "time_verified_at": "DATETIME NULL",
    "stream_probe_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
    "stream_probe_attempts": "INT NOT NULL DEFAULT 0",
    "last_stream_probe_at": "DATETIME NULL",
    "last_stream_probe_error": "TEXT NULL",
    "stream_detected_at": "DATETIME NULL",
}


def ensure_transcript_archive_schema() -> None:
    """Create the bounded transcript archive used for replay and recovery."""
    query = text("""
        CREATE TABLE IF NOT EXISTS transcript_segments (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            call_id VARCHAR(128) NOT NULL,
            ticker VARCHAR(20) NOT NULL,
            sequence_no INT NOT NULL,
            start_ms BIGINT NOT NULL,
            end_ms BIGINT NOT NULL,
            text_chunk TEXT NOT NULL,
            speaker VARCHAR(128) NULL,
            source_timestamp BIGINT NULL,
            is_session_end BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_transcript_segments_call_sequence (call_id, sequence_no),
            INDEX idx_transcript_segments_ticker_created (ticker, created_at),
            INDEX idx_transcript_segments_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with engine.begin() as conn:
        conn.execute(query)


def archive_transcript_segment(
    payload: Dict[str, Any],
    *,
    ensure_schema: bool = True,
) -> None:
    """Persist one STT segment without storing the source audio."""
    if ensure_schema:
        ensure_transcript_archive_schema()
    query = text("""
        INSERT INTO transcript_segments (
            call_id, ticker, sequence_no, start_ms, end_ms, text_chunk,
            speaker, source_timestamp, is_session_end
        ) VALUES (
            :call_id, :ticker, :sequence_no, :start_ms, :end_ms, :text_chunk,
            :speaker, :source_timestamp, :is_session_end
        )
        ON DUPLICATE KEY UPDATE
            ticker = VALUES(ticker),
            start_ms = VALUES(start_ms),
            end_ms = VALUES(end_ms),
            text_chunk = VALUES(text_chunk),
            speaker = VALUES(speaker),
            source_timestamp = VALUES(source_timestamp),
            is_session_end = VALUES(is_session_end)
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
    }
    if not params["call_id"] or not params["ticker"] or not params["text_chunk"]:
        return
    with engine.begin() as conn:
        conn.execute(query, params)


def purge_transcript_segments(
    retention_days: int = 180,
    *,
    batch_size: int = 10000,
    max_batches: int = 10,
) -> int:
    """Delete old transcript rows in bounded batches to avoid a long table lock."""
    ensure_transcript_archive_schema()
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
        with engine.begin() as conn:
            result = conn.execute(query)
            removed = int(result.rowcount or 0)
        deleted += removed
        if removed < batch:
            break
    return deleted


def get_archived_transcript_segments(call_id: str) -> List[Dict[str, Any]]:
    """Read one call's archived transcript in sequence order."""
    ensure_transcript_archive_schema()
    query = text("""
        SELECT call_id, ticker, sequence_no, start_ms, end_ms, text_chunk,
               speaker, source_timestamp, is_session_end, created_at
        FROM transcript_segments
        WHERE call_id = :call_id
        ORDER BY sequence_no ASC
    """)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, {"call_id": call_id})]


def ensure_schedule_time_schema() -> None:
    """Add schedule-verification fields to existing local MySQL volumes."""
    with engine.begin() as conn:
        existing_columns = {
            row[0]
            for row in conn.execute(text("SHOW COLUMNS FROM calls"))
        }
        for column, definition in SCHEDULE_TIME_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(text(f"ALTER TABLE calls ADD COLUMN {column} {definition}"))

        indexes = {
            row[2]
            for row in conn.execute(text("SHOW INDEX FROM calls"))
        }
        if "idx_calls_status_scheduled_at_utc" not in indexes:
            conn.execute(
                text(
                    "CREATE INDEX idx_calls_status_scheduled_at_utc "
                    "ON calls (status, scheduled_at_utc)"
                )
            )
        if "idx_calls_stream_probe" not in indexes:
            conn.execute(
                text(
                    "CREATE INDEX idx_calls_stream_probe "
                    "ON calls (status, earning_at, last_stream_probe_at)"
                )
            )


def ensure_webcast_recipe_schema() -> None:
    """Create the data-driven browser recipes table on existing MySQL volumes."""
    query = text("""
        CREATE TABLE IF NOT EXISTS webcast_recipes (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            recipe_key CHAR(64) NOT NULL,
            domain VARCHAR(255) NOT NULL,
            selector_json TEXT NOT NULL,
            frame_hostname VARCHAR(255) NULL,
            target_text VARCHAR(500) NULL,
            target_href_path VARCHAR(1024) NULL,
            strategy VARCHAR(64) NOT NULL,
            lifecycle VARCHAR(32) NOT NULL DEFAULT 'unknown',
            confidence DECIMAL(5, 4) NOT NULL DEFAULT 0,
            state VARCHAR(32) NOT NULL DEFAULT 'candidate',
            success_count INT NOT NULL DEFAULT 0,
            failure_count INT NOT NULL DEFAULT 0,
            last_verified_at DATETIME NULL,
            last_error TEXT NULL,
            evidence_json TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_webcast_recipes_key (recipe_key),
            INDEX idx_webcast_recipes_domain_state (domain, state, updated_at),
            INDEX idx_webcast_recipes_lifecycle (domain, lifecycle, state, updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with engine.begin() as conn:
        conn.execute(query)
        columns = {row[0] for row in conn.execute(text("SHOW COLUMNS FROM webcast_recipes"))}
        if "lifecycle" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE webcast_recipes "
                    "ADD COLUMN lifecycle VARCHAR(32) NOT NULL DEFAULT 'unknown' AFTER strategy"
                )
            )
        indexes = {row[2] for row in conn.execute(text("SHOW INDEX FROM webcast_recipes"))}
        if "idx_webcast_recipes_lifecycle" not in indexes:
            conn.execute(
                text(
                    "CREATE INDEX idx_webcast_recipes_lifecycle "
                    "ON webcast_recipes (domain, lifecycle, state, updated_at)"
                )
            )


def get_verified_webcast_recipes(
    domain: str,
    lifecycles: tuple[str, ...] = ("unknown",),
) -> List[Dict[str, Any]]:
    """Return audio-verified recipes compatible with the current event lifecycle."""
    if not domain:
        return []
    ensure_webcast_recipe_schema()
    lifecycle_values = tuple(dict.fromkeys(value.lower() for value in lifecycles if value)) or ("unknown",)
    lifecycle_params = {f"lifecycle_{index}": value for index, value in enumerate(lifecycle_values)}
    lifecycle_placeholders = ", ".join(f":{key}" for key in lifecycle_params)
    query = text(f"""
        SELECT id, recipe_key, domain, selector_json, frame_hostname, target_text,
               target_href_path, strategy, lifecycle, confidence, state, success_count,
               failure_count, last_verified_at, last_error, evidence_json
        FROM webcast_recipes
        WHERE domain = :domain
          AND state = 'verified'
          AND failure_count < 3
          AND lifecycle IN ({lifecycle_placeholders})
        ORDER BY FIELD(lifecycle, {lifecycle_placeholders}), success_count DESC, confidence DESC, updated_at DESC
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"domain": domain.lower(), **lifecycle_params})
        return [dict(row._mapping) for row in result]


def get_generalized_webcast_patterns(
    lifecycles: tuple[str, ...] = ("unknown", "replay", "live", "pre_live"),
) -> List[Dict[str, Any]]:
    """Return audio-verified label/href evidence reusable across IR domains."""
    ensure_webcast_recipe_schema()
    lifecycle_values = tuple(dict.fromkeys(value.lower() for value in lifecycles if value)) or ("unknown",)
    params = {f"lifecycle_{index}": value for index, value in enumerate(lifecycle_values)}
    placeholders = ", ".join(f":{key}" for key in params)
    query = text(f"""
        SELECT target_text, target_href_path, success_count
        FROM webcast_recipes
        WHERE state = 'verified'
          AND failure_count < 3
          AND lifecycle IN ({placeholders})
        ORDER BY success_count DESC, last_verified_at DESC
    """)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, params)]


def get_verified_webcast_recipes_for_benchmark() -> List[Dict[str, Any]]:
    """Return complete verified recipe evidence for offline selector comparisons."""
    ensure_webcast_recipe_schema()
    query = text("""
        SELECT id, target_text, target_href_path, success_count, evidence_json
        FROM webcast_recipes
        WHERE state = 'verified' AND failure_count < 3
        ORDER BY id
    """)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def save_webcast_recipe(recipe: Dict[str, Any]) -> int:
    """Store a learned candidate; it becomes verified only after audible replay."""
    ensure_webcast_recipe_schema()
    query = text("""
        INSERT INTO webcast_recipes (
            recipe_key, domain, selector_json, frame_hostname, target_text,
            target_href_path, strategy, lifecycle, confidence, state, evidence_json
        ) VALUES (
            :recipe_key, :domain, :selector_json, :frame_hostname, :target_text,
            :target_href_path, :strategy, :lifecycle, :confidence, 'candidate', :evidence_json
        )
        ON DUPLICATE KEY UPDATE
            target_text = VALUES(target_text),
            target_href_path = VALUES(target_href_path),
            strategy = VALUES(strategy),
            lifecycle = VALUES(lifecycle),
            confidence = GREATEST(confidence, VALUES(confidence)),
            evidence_json = VALUES(evidence_json),
            updated_at = CURRENT_TIMESTAMP
    """)
    with engine.begin() as conn:
        conn.execute(query, recipe)
        recipe_id = conn.execute(
            text("SELECT id FROM webcast_recipes WHERE recipe_key = :recipe_key"),
            {"recipe_key": recipe["recipe_key"]},
        ).scalar_one()
    return int(recipe_id)


def record_webcast_recipe_outcome(recipe_id: int, *, success: bool, error: str | None = None) -> None:
    """Promote only audio-verified recipes and retire repeatedly failing ones."""
    ensure_webcast_recipe_schema()
    if success:
        query = text("""
            UPDATE webcast_recipes
            SET state = 'verified',
                success_count = success_count + 1,
                last_verified_at = NOW(),
                last_error = NULL
            WHERE id = :recipe_id
        """)
        params = {"recipe_id": recipe_id}
    else:
        query = text("""
            UPDATE webcast_recipes
            SET failure_count = failure_count + 1,
                state = CASE WHEN failure_count + 1 >= 3 THEN 'disabled' ELSE state END,
                last_error = :error
            WHERE id = :recipe_id
        """)
        params = {"recipe_id": recipe_id, "error": error[:1000] if error else "audio not detected"}
    with engine.begin() as conn:
        conn.execute(query, params)


def ensure_webcast_learning_target_schema() -> None:
    """Create resumable per-company learning state for the full IR universe."""
    query = text("""
        CREATE TABLE IF NOT EXISTS webcast_learning_targets (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            target_key CHAR(64) NOT NULL,
            call_id BIGINT NULL,
            ticker VARCHAR(20) NOT NULL,
            target_url VARCHAR(2048) NOT NULL,
            target_kind VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            attempt_count INT NOT NULL DEFAULT 0,
            audible_count INT NOT NULL DEFAULT 0,
            last_attempt_at DATETIME NULL,
            last_audible_at DATETIME NULL,
            last_error TEXT NULL,
            last_output TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_webcast_learning_targets_key (target_key),
            INDEX idx_webcast_learning_targets_status (status, last_attempt_at),
            INDEX idx_webcast_learning_targets_ticker (ticker)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with engine.begin() as conn:
        conn.execute(query)


def get_webcast_learning_targets(limit: int | None = None) -> List[Dict[str, Any]]:
    """Return one best available replay entrypoint for every active company."""
    ensure_webcast_learning_target_schema()
    query = """
        SELECT c.id AS call_id, c.ticker, c.call_year, c.quarter,
               c.earning_at, c.scheduled_at_utc,
               c.webcast_url, c.event_url, s.ir_url
        FROM calls c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE s.active = TRUE
          AND c.status = 'upcoming'
        UNION ALL
        SELECT NULL AS call_id, s.ticker, NULL AS call_year, NULL AS quarter,
               NULL AS earning_at, NULL AS scheduled_at_utc,
               NULL AS webcast_url, NULL AS event_url, s.ir_url
        FROM stocks s
        WHERE s.active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM calls c WHERE c.ticker = s.ticker AND c.status = 'upcoming'
          )
        ORDER BY ticker ASC
    """
    if limit is not None:
        query += " LIMIT :limit"

    with engine.connect() as conn:
        result = conn.execute(text(query), {"limit": max(1, limit)} if limit is not None else {})
        rows = [dict(row._mapping) for row in result]

    targets: list[Dict[str, Any]] = []
    for row in rows:
        target_url, target_kind = _best_webcast_learning_url(row)
        if not target_url:
            continue
        target = {
            "call_id": row["call_id"],
            "ticker": row["ticker"],
            "call_year": row["call_year"],
            "quarter": row["quarter"],
            "earning_at": row["earning_at"],
            "scheduled_at_utc": row["scheduled_at_utc"],
            "ir_url": target_url,
            "target_url": target_url,
            "target_kind": target_kind,
        }
        target["target_key"] = _webcast_learning_target_key(target)
        targets.append(target)
    return prioritize_webcast_learning_targets(targets)


def claim_webcast_learning_target(target: Dict[str, Any], cooldown_minutes: int = 1440) -> bool:
    """Atomically reserve a universe target while allowing safe later retries."""
    ensure_webcast_learning_target_schema()
    insert = text("""
        INSERT IGNORE INTO webcast_learning_targets (
            target_key, call_id, ticker, target_url, target_kind
        ) VALUES (
            :target_key, :call_id, :ticker, :target_url, :target_kind
        )
    """)
    update = text("""
        UPDATE webcast_learning_targets
        SET call_id = :call_id,
            ticker = :ticker,
            target_url = :target_url,
            target_kind = :target_kind,
            status = 'probing',
            attempt_count = attempt_count + 1,
            last_attempt_at = NOW(),
            last_error = NULL,
            last_output = NULL
        WHERE target_key = :target_key
          AND (
              last_attempt_at IS NULL
              OR last_attempt_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    params = {**target, "cooldown_minutes": max(0, cooldown_minutes)}
    with engine.begin() as conn:
        conn.execute(insert, params)
        result = conn.execute(update, params)
        return result.rowcount == 1


def record_webcast_learning_target_outcome(
    target: Dict[str, Any],
    *,
    status: str,
    error: str | None = None,
    output: str | None = None,
) -> None:
    """Persist a full-universe probe result for progress reporting and retries."""
    ensure_webcast_learning_target_schema()
    query = text("""
        UPDATE webcast_learning_targets
        SET status = :status,
            audible_count = audible_count + CASE WHEN :status = 'audible' THEN 1 ELSE 0 END,
            last_audible_at = CASE WHEN :status = 'audible' THEN NOW() ELSE last_audible_at END,
            last_error = :error,
            last_output = :output
        WHERE target_key = :target_key
    """)
    with engine.begin() as conn:
        conn.execute(
            query,
            {
                "target_key": target["target_key"],
                "status": status,
                "error": error[:1000] if error else None,
                "output": output[-4000:] if output else None,
            },
        )


def get_webcast_learning_summary() -> List[Dict[str, Any]]:
    ensure_webcast_learning_target_schema()
    query = text("""
        SELECT status, COUNT(*) AS target_count,
               SUM(attempt_count) AS attempts,
               SUM(audible_count) AS audible_count
        FROM webcast_learning_targets
        GROUP BY status
        ORDER BY status
    """)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def ensure_webcast_replay_target_schema() -> None:
    """Create resumable targets for historical earnings-webcast replay verification."""
    query = text("""
        CREATE TABLE IF NOT EXISTS webcast_replay_targets (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            target_key CHAR(64) NOT NULL,
            call_id BIGINT NULL,
            ticker VARCHAR(20) NOT NULL,
            call_year INT NULL,
            quarter VARCHAR(8) NULL,
            earning_at DATETIME NULL,
            target_url VARCHAR(2048) NOT NULL,
            source_kind VARCHAR(32) NOT NULL DEFAULT 'search',
            source_title VARCHAR(500) NULL,
            source_snippet TEXT NULL,
            provider_domain VARCHAR(255) NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'discovered',
            attempt_count INT NOT NULL DEFAULT 0,
            audible_count INT NOT NULL DEFAULT 0,
            last_attempt_at DATETIME NULL,
            last_audible_at DATETIME NULL,
            last_error TEXT NULL,
            last_output TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_webcast_replay_targets_key (target_key),
            INDEX idx_webcast_replay_targets_status (status, last_attempt_at),
            INDEX idx_webcast_replay_targets_call (call_id, ticker)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with engine.begin() as conn:
        conn.execute(query)
        call_id_column = conn.execute(
            text(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'webcast_replay_targets' "
                "AND COLUMN_NAME = 'call_id'"
            )
        ).scalar_one_or_none()
        if call_id_column == "NO":
            conn.execute(
                text(
                    "ALTER TABLE webcast_replay_targets "
                    "MODIFY COLUMN call_id BIGINT NULL"
                )
            )


def ensure_webcast_replay_discovery_schema() -> None:
    """Track replay searches per ticker so a 500-company run can resume safely."""
    ensure_webcast_replay_target_schema()
    query = text("""
        CREATE TABLE IF NOT EXISTS webcast_replay_discovery (
            ticker VARCHAR(20) PRIMARY KEY,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            attempt_count INT NOT NULL DEFAULT 0,
            candidate_count INT NOT NULL DEFAULT 0,
            last_attempt_at DATETIME NULL,
            last_error TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_webcast_replay_discovery_status (status, last_attempt_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with engine.begin() as conn:
        conn.execute(query)
        conn.execute(
            text("""
                INSERT IGNORE INTO webcast_replay_discovery (
                    ticker, status, candidate_count
                )
                SELECT ticker, 'discovered', COUNT(*)
                FROM webcast_replay_targets
                GROUP BY ticker
            """)
        )
        conn.execute(
            text("""
                UPDATE webcast_replay_discovery discovery
                JOIN (
                    SELECT ticker, COUNT(*) AS candidate_count
                    FROM webcast_replay_targets
                    GROUP BY ticker
                ) targets ON targets.ticker = discovery.ticker
                SET discovery.status = 'discovered',
                    discovery.candidate_count = GREATEST(
                        discovery.candidate_count,
                        targets.candidate_count
                    )
                WHERE discovery.status = 'error'
            """)
        )


def get_historical_replay_calls(limit: int | None = None) -> List[Dict[str, Any]]:
    """Return one replay-search context for every active stock."""
    query = """
        SELECT recent_call.id AS call_id,
               s.ticker,
               COALESCE(recent_call.call_year, YEAR(CURDATE())) AS call_year,
               recent_call.quarter,
               COALESCE(recent_call.earning_at, DATE_SUB(CURDATE(), INTERVAL 1 DAY)) AS earning_at,
               s.company_name,
               s.ir_url
        FROM stocks s
        LEFT JOIN calls recent_call
          ON recent_call.id = (
              SELECT historical_call.id
              FROM calls historical_call
              WHERE historical_call.ticker = s.ticker
                AND historical_call.earning_at < CURDATE()
              ORDER BY historical_call.earning_at DESC, historical_call.id DESC
              LIMIT 1
          )
        WHERE s.active = TRUE
        ORDER BY s.ticker ASC
    """
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def claim_historical_replay_discovery(
    call: Dict[str, Any],
    *,
    cooldown_minutes: int = 10080,
    force: bool = False,
) -> bool:
    """Reserve one ticker's Serper search without repeating completed discovery."""
    ensure_webcast_replay_discovery_schema()
    ticker = str(call["ticker"]).upper()
    insert = text("""
        INSERT IGNORE INTO webcast_replay_discovery (ticker)
        VALUES (:ticker)
    """)
    allowed_statuses = (
        "('pending', 'no_candidate', 'error', 'searching', 'discovered')"
        if force
        else "('pending', 'no_candidate', 'error', 'searching')"
    )
    update = text(f"""
        UPDATE webcast_replay_discovery
        SET status = 'searching',
            attempt_count = attempt_count + 1,
            last_attempt_at = NOW(),
            last_error = NULL
        WHERE ticker = :ticker
          AND status IN {allowed_statuses}
          AND (
              :force = TRUE
              OR last_attempt_at IS NULL
              OR last_attempt_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    with engine.begin() as conn:
        conn.execute(insert, {"ticker": ticker})
        result = conn.execute(
            update,
            {
                "ticker": ticker,
                "force": force,
                "cooldown_minutes": max(0, cooldown_minutes),
            },
        )
        return result.rowcount == 1


def record_historical_replay_discovery(
    ticker: str,
    *,
    status: str,
    candidate_count: int = 0,
    error: str | None = None,
) -> None:
    """Persist one ticker's replay-search outcome."""
    ensure_webcast_replay_discovery_schema()
    query = text("""
        UPDATE webcast_replay_discovery
        SET status = CASE
                WHEN :status = 'error' AND candidate_count > 0 THEN 'discovered'
                ELSE :status
            END,
            candidate_count = CASE
                WHEN :status = 'error' AND candidate_count > 0 THEN candidate_count
                ELSE :candidate_count
            END,
            last_error = :error
        WHERE ticker = :ticker
    """)
    with engine.begin() as conn:
        conn.execute(
            query,
            {
                "ticker": ticker.upper(),
                "status": status,
                "candidate_count": max(0, candidate_count),
                "error": error[:1000] if error else None,
            },
        )


def get_historical_replay_discovery_summary() -> List[Dict[str, Any]]:
    ensure_webcast_replay_discovery_schema()
    query = text("""
        SELECT status, COUNT(*) AS ticker_count,
               SUM(attempt_count) AS attempts,
               SUM(candidate_count) AS candidates
        FROM webcast_replay_discovery
        GROUP BY status
        ORDER BY status
    """)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_historical_replay_discovery_tickers(statuses: set[str]) -> set[str]:
    """Return tickers whose replay discovery state matches an explicit retry set."""
    ensure_webcast_replay_discovery_schema()
    normalized = sorted({status.strip().lower() for status in statuses if status.strip()})
    if not normalized:
        return set()
    params = {f"status_{index}": status for index, status in enumerate(normalized)}
    placeholders = ", ".join(f":{name}" for name in params)
    query = text(
        f"SELECT ticker FROM webcast_replay_discovery "
        f"WHERE status IN ({placeholders})"
    )
    with engine.connect() as conn:
        return {str(row[0]).upper() for row in conn.execute(query, params)}


def save_historical_replay_targets(
    call: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> int:
    """Persist official-looking replay candidates without changing the original call record."""
    ensure_webcast_replay_target_schema()
    query = text("""
        INSERT INTO webcast_replay_targets (
            target_key, call_id, ticker, call_year, quarter, earning_at, target_url,
            source_kind, source_title, source_snippet, provider_domain
        ) VALUES (
            :target_key, :call_id, :ticker, :call_year, :quarter, :earning_at, :target_url,
            :source_kind, :source_title, :source_snippet, :provider_domain
        )
        ON DUPLICATE KEY UPDATE
            source_kind = VALUES(source_kind),
            source_title = VALUES(source_title),
            source_snippet = VALUES(source_snippet),
            provider_domain = VALUES(provider_domain),
            updated_at = CURRENT_TIMESTAMP
    """)
    saved = 0
    with engine.begin() as conn:
        for candidate in candidates:
            target_url = str(candidate.get("target_url") or "").strip()
            if not target_url:
                continue
            params = {
                "target_key": _webcast_replay_target_key(call, target_url),
                "call_id": call["call_id"],
                "ticker": str(call["ticker"]).upper(),
                "call_year": call.get("call_year"),
                "quarter": call.get("quarter"),
                "earning_at": call.get("earning_at"),
                "target_url": target_url,
                "source_kind": str(candidate.get("source_kind") or "search")[:32],
                "source_title": str(candidate.get("source_title") or "")[:500] or None,
                "source_snippet": str(candidate.get("source_snippet") or "")[:4000] or None,
                "provider_domain": str(candidate.get("provider_domain") or "")[:255] or None,
            }
            conn.execute(query, params)
            saved += 1
    return saved


def get_historical_replay_targets(
    limit: int | None = None,
    *,
    include_registration_required: bool = False,
    include_auth_required: bool = False,
    auth_required_only: bool = False,
) -> List[Dict[str, Any]]:
    """Return unverified historical replays, prioritizing newly discovered candidates."""
    ensure_webcast_replay_target_schema()
    status_filter = (
        "'auth_required'"
        if auth_required_only
        else "'discovered', 'no_audio', 'no_candidate', 'error', 'capture_runtime_failed'"
        + (", 'registration_required'" if include_registration_required else "")
        + (", 'auth_required'" if include_auth_required else "")
    )
    query = """
        SELECT target_key, call_id, ticker, call_year, quarter, earning_at, target_url,
               source_kind, source_title, source_snippet, provider_domain, status,
               attempt_count, audible_count, last_attempt_at, last_error
        FROM webcast_replay_targets
        WHERE status IN ({status_filter})
          AND NOT EXISTS (
              SELECT 1
              FROM webcast_replay_targets audible_target
              WHERE audible_target.ticker = webcast_replay_targets.ticker
                AND audible_target.status = 'audible'
          )
        ORDER BY CASE status WHEN 'discovered' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
                 CASE source_kind
                     WHEN 'serper_direct' THEN 0
                     WHEN 'serper_announcement' THEN 1
                     WHEN 'serper_archive' THEN 2
                     ELSE 3
                 END,
                 earning_at DESC, ticker ASC
    """
    query = query.format(
        status_filter=status_filter,
    )
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def recover_stale_historical_replay_targets(stale_minutes: int = 10) -> int:
    """Return interrupted browser probes to the retry queue."""
    ensure_webcast_replay_target_schema()
    query = text("""
        UPDATE webcast_replay_targets
        SET status = 'error',
            last_error = 'previous replay probe was interrupted'
        WHERE status = 'probing'
          AND last_attempt_at <= DATE_SUB(NOW(), INTERVAL :stale_minutes MINUTE)
    """)
    with engine.begin() as conn:
        result = conn.execute(query, {"stale_minutes": max(1, stale_minutes)})
        return int(result.rowcount)


def claim_historical_replay_target(target: Dict[str, Any], cooldown_minutes: int = 10080) -> bool:
    """Reserve one historical replay URL so only one browser probe handles it at a time."""
    ensure_webcast_replay_target_schema()
    query = text("""
        UPDATE webcast_replay_targets
        SET status = 'probing',
            attempt_count = attempt_count + 1,
            last_attempt_at = NOW(),
            last_error = NULL,
            last_output = NULL
        WHERE target_key = :target_key
          AND (
              last_attempt_at IS NULL
              OR last_attempt_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    with engine.begin() as conn:
        result = conn.execute(
            query,
            {"target_key": target["target_key"], "cooldown_minutes": max(0, cooldown_minutes)},
        )
        return result.rowcount == 1


def record_historical_replay_outcome(
    target: Dict[str, Any],
    *,
    status: str,
    error: str | None = None,
    output: str | None = None,
) -> None:
    """Record browser/audio proof for one historical replay candidate."""
    ensure_webcast_replay_target_schema()
    query = text("""
        UPDATE webcast_replay_targets
        SET status = :status,
            audible_count = audible_count + CASE WHEN :status = 'audible' THEN 1 ELSE 0 END,
            last_audible_at = CASE WHEN :status = 'audible' THEN NOW() ELSE last_audible_at END,
            last_error = :error,
            last_output = :output
        WHERE target_key = :target_key
    """)
    with engine.begin() as conn:
        conn.execute(
            query,
            {
                "target_key": target["target_key"],
                "status": status,
                "error": error[:1000] if error else None,
                "output": output[-4000:] if output else None,
            },
        )


def get_historical_replay_summary() -> List[Dict[str, Any]]:
    ensure_webcast_replay_target_schema()
    query = text("""
        SELECT status, COUNT(*) AS target_count, SUM(attempt_count) AS attempts,
               SUM(audible_count) AS audible_count
        FROM webcast_replay_targets
        GROUP BY status
        ORDER BY status
    """)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_historical_replay_error_records(limit: int | None = None) -> List[Dict[str, Any]]:
    """Return failed replay probes for root-cause analysis without retrying them."""
    ensure_webcast_replay_target_schema()
    query = """
        SELECT ticker, provider_domain, target_url, attempt_count, last_error
        FROM webcast_replay_targets
        WHERE status = 'error'
        ORDER BY attempt_count DESC, ticker ASC
    """
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def get_historical_replay_coverage_summary() -> Dict[str, int]:
    """Return ticker-level discovery and audible coverage for the active universe."""
    ensure_webcast_replay_discovery_schema()
    ensure_webcast_replay_target_schema()
    query = text("""
        SELECT
            (SELECT COUNT(*) FROM stocks WHERE active = TRUE) AS active_tickers,
            (
                SELECT COUNT(*)
                FROM webcast_replay_discovery
                WHERE status = 'discovered'
            ) AS discovered_tickers,
            (
                SELECT COUNT(DISTINCT ticker)
                FROM webcast_replay_targets
            ) AS candidate_tickers,
            (
                SELECT COUNT(DISTINCT ticker)
                FROM webcast_replay_targets
                WHERE status = 'audible'
            ) AS audible_tickers
    """)
    with engine.connect() as conn:
        row = conn.execute(query).one()
        return {key: int(value or 0) for key, value in row._mapping.items()}


def _webcast_replay_target_key(call: Dict[str, Any], target_url: str) -> str:
    source = "|".join([str(call["call_id"]), str(call["ticker"]).upper(), target_url])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _best_webcast_learning_url(row: Dict[str, Any]) -> tuple[str | None, str]:
    for field, kind in (
        ("webcast_url", "webcast_url"),
        ("event_url", "event_url"),
        ("ir_url", "ir_url"),
    ):
        value = str(row.get(field) or "").strip()
        if value:
            return value, kind
    return None, "missing"


def prioritize_webcast_learning_targets(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Try explicit webcast pages before event pages and generic IR homepages."""
    priority = {"webcast_url": 0, "event_url": 1, "ir_url": 2}
    return sorted(
        targets,
        key=lambda target: (priority.get(str(target.get("target_kind")), 3), str(target["ticker"])),
    )


def _webcast_learning_target_key(target: Dict[str, Any]) -> str:
    source = "|".join(
        [
            str(target.get("call_id") or "stock"),
            str(target["ticker"]).upper(),
            str(target["target_kind"]),
            str(target["target_url"]),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()

# --- 1. 종목 리스트 저장 (stocks 테이블) ---
def save_stocks(stock_list: List[Dict]):
    """S&P 500 등 종목 마스터 정보를 저장"""
    if not stock_list: return
    
    query = text("""
        INSERT INTO stocks (ticker, company_name, sector)
        VALUES (:ticker, :company_name, :sector)
        ON DUPLICATE KEY UPDATE 
            company_name = VALUES(company_name),
            sector = VALUES(sector)
    """)
    
    with engine.begin() as conn:
        for stock in stock_list:
            conn.execute(query, stock)
    print(f"💾 [Stocks] {len(stock_list)}개 종목 동기화 완료.")

# --- 2. 어닝 일정 저장 (calls 테이블) ---
def save_earnings_schedules(schedules: List[Dict]):
    """yfinance 등으로 수집한 어닝콜 날짜 정보를 저장"""
    if not schedules: return

    query = text("""
        INSERT INTO calls (ticker, earning_at, call_year, quarter, status)
        VALUES (:ticker, :earning_date, :call_year, :quarter, 'upcoming')
        ON DUPLICATE KEY UPDATE 
            earning_at = VALUES(earning_at),
            status = IF(status = 'completed', 'completed', 'upcoming')
    """)

    with engine.begin() as conn:
        for item in schedules:
            # 캘린더 날짜를 기반으로 연도/분기 계산 로직 추가 가능
            item['call_year'] = item['earning_date'].year
            item['quarter'] = f"Q{(item['earning_date'].month-1)//3 + 1}"
            conn.execute(query, item)
    print(f"💾 [Schedules] {len(schedules)}개 일정 업데이트 완료.")

# --- 3. 스트림 링크 업데이트 (calls 테이블) ---
def update_stream_link(ticker: str, video_url: str):
    """유튜브 등에서 찾은 실시간 링크를 기존 일정에 업데이트"""
    query = text("""
        UPDATE calls 
        SET video_url = :video_url, status = 'live'
        WHERE ticker = :ticker AND status = 'upcoming'
        ORDER BY earning_at ASC LIMIT 1
    """)
    
    with engine.begin() as conn:
        conn.execute(query, {"ticker": ticker, "video_url": video_url})


def update_call_video_url(call_id: int, video_url: str):
    """브라우저 자동화로 확보한 실제 미디어 URL을 콜 레코드에 저장한다."""
    query = text("""
        UPDATE calls
        SET video_url = :video_url
        WHERE id = :call_id
    """)

    with engine.begin() as conn:
        conn.execute(query, {"call_id": call_id, "video_url": video_url})


def get_imminent_calls(minutes_ahead: int = 5, grace_minutes: int = 1) -> List[Dict]:
    """STT 워커가 처리해야 할 임박한 어닝콜을 조회한다."""
    ensure_schedule_time_schema()
    query = text("""
        SELECT
            c.id,
            c.ticker,
            c.earning_at,
            c.scheduled_at_utc,
            c.call_year,
            c.quarter,
            c.status,
            c.video_url,
            s.company_name,
            s.ir_url
        FROM calls c
        LEFT JOIN stocks s ON s.ticker = c.ticker
        WHERE c.status IN ('upcoming', 'live')
          AND c.time_verification_status = 'verified'
          AND c.scheduled_at_utc BETWEEN
              DATE_SUB(NOW(), INTERVAL :grace_minutes MINUTE)
              AND DATE_ADD(NOW(), INTERVAL :minutes_ahead MINUTE)
        ORDER BY c.scheduled_at_utc ASC
    """)

    with engine.connect() as conn:
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
) -> List[Dict[str, Any]]:
    """Return future calls whose exact official start time still needs verification."""
    ensure_schedule_time_schema()
    query = """
        SELECT c.id, c.ticker, c.earning_at, s.company_name, s.ir_url
        FROM calls c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE c.status = 'upcoming'
          AND c.earning_at >= CURDATE()
          AND c.time_verification_status <> 'verified'
    """
    params: Dict[str, Any] = {}
    if days_ahead is not None:
        query += " AND c.earning_at < DATE_ADD(CURDATE(), INTERVAL :days_ahead DAY)"
        params["days_ahead"] = days_ahead
    query += " ORDER BY c.earning_at ASC, c.ticker ASC"
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = limit

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        return [dict(row._mapping) for row in result]


def update_verified_schedule_time(call_id: int, evidence: Dict[str, Any]) -> None:
    """Persist an official, date-matched event time and its supporting evidence."""
    ensure_schedule_time_schema()
    query = text("""
        UPDATE calls
        SET scheduled_at_utc = :scheduled_at_utc,
            source_timezone = :source_timezone,
            event_url = :event_url,
            webcast_url = :webcast_url,
            schedule_source = :schedule_source,
            schedule_evidence = :schedule_evidence,
            time_verification_status = 'verified',
            time_verified_at = UTC_TIMESTAMP()
        WHERE id = :call_id
    """)
    with engine.begin() as conn:
        conn.execute(query, {"call_id": call_id, **evidence})


def get_date_based_stream_candidates(
    days_ahead: int = 1,
    limit: int = 20,
    cooldown_minutes: int = 15,
    near_start_minutes: int = 20,
    near_end_minutes: int = 180,
    near_cooldown_minutes: int = 1,
) -> List[Dict[str, Any]]:
    """Return date-matched calls that are due for another webcast probe."""
    ensure_schedule_time_schema()
    event_timezone = ZoneInfo(os.getenv("DATE_STREAM_WATCH_TIMEZONE", "America/New_York"))
    start_date = datetime.now(event_timezone).date()
    end_date = start_date + timedelta(days=max(1, days_ahead))
    query = text("""
        SELECT c.id, c.ticker, c.earning_at, c.scheduled_at_utc,
               c.call_year, c.quarter, c.status,
               c.video_url, c.stream_probe_attempts, s.company_name, s.ir_url
        FROM calls c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE c.status = 'upcoming'
          AND c.earning_at >= :start_date
          AND c.earning_at < :end_date
          AND (
              c.last_stream_probe_at IS NULL
              OR c.last_stream_probe_at <= DATE_SUB(
                  UTC_TIMESTAMP(), INTERVAL :cooldown_minutes MINUTE
              )
              OR (
                  c.scheduled_at_utc IS NOT NULL
                  AND c.scheduled_at_utc BETWEEN
                      DATE_SUB(UTC_TIMESTAMP(), INTERVAL :near_end_minutes MINUTE)
                      AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL :near_start_minutes MINUTE)
                  AND c.last_stream_probe_at <= DATE_SUB(
                      UTC_TIMESTAMP(), INTERVAL :near_cooldown_minutes MINUTE
                  )
              )
          )
        ORDER BY
            CASE
                WHEN c.scheduled_at_utc IS NOT NULL
                 AND c.scheduled_at_utc BETWEEN
                     DATE_SUB(UTC_TIMESTAMP(), INTERVAL :near_end_minutes MINUTE)
                     AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL :near_start_minutes MINUTE)
                THEN 0
                ELSE 1
            END,
            c.earning_at ASC,
            c.ticker ASC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        result = conn.execute(
            query,
            {
                "start_date": start_date,
                "end_date": end_date,
                "limit": max(1, limit),
                "cooldown_minutes": max(1, cooldown_minutes),
                "near_start_minutes": max(0, near_start_minutes),
                "near_end_minutes": max(0, near_end_minutes),
                "near_cooldown_minutes": max(1, near_cooldown_minutes),
            },
        )
        return [dict(row._mapping) for row in result]


def claim_stream_probe(call_id: int, cooldown_minutes: int = 15) -> bool:
    """Atomically claim one date-based probe so scheduler ticks do not duplicate it."""
    ensure_schedule_time_schema()
    query = text("""
        UPDATE calls
        SET stream_probe_status = 'probing',
            stream_probe_attempts = stream_probe_attempts + 1,
            last_stream_probe_at = NOW(),
            last_stream_probe_error = NULL
        WHERE id = :call_id
          AND status = 'upcoming'
          AND (
              last_stream_probe_at IS NULL
              OR last_stream_probe_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    with engine.begin() as conn:
        result = conn.execute(
            query,
            {"call_id": call_id, "cooldown_minutes": max(1, cooldown_minutes)},
        )
        return result.rowcount == 1


def record_stream_probe(call_id: int, stream_ready: bool, error: str | None = None) -> None:
    """Record date-based discovery state without changing the STT call lifecycle."""
    query = text("""
        UPDATE calls
        SET stream_probe_status = :stream_probe_status,
            stream_detected_at = CASE WHEN :stream_ready THEN NOW() ELSE stream_detected_at END,
            last_stream_probe_error = :error
        WHERE id = :call_id
    """)
    with engine.begin() as conn:
        conn.execute(
            query,
            {
                "call_id": call_id,
                "stream_ready": stream_ready,
                "stream_probe_status": "stream_ready" if stream_ready else "pending",
                "error": error[:1000] if error else None,
            },
        )


def mark_call_running(call_id: int) -> bool:
    """중복 실행 방지를 위해 upcoming/live 상태의 콜 하나를 running으로 선점한다."""
    query = text("""
        UPDATE calls
        SET status = 'running'
        WHERE id = :call_id
          AND status IN ('upcoming', 'live')
    """)

    with engine.begin() as conn:
        result = conn.execute(query, {"call_id": call_id})
        return result.rowcount == 1


def update_call_status(call_id: int, status: str):
    """STT 워커 상태를 calls 테이블에 반영한다."""
    query = text("""
        UPDATE calls
        SET status = :status
        WHERE id = :call_id
    """)

    with engine.begin() as conn:
        conn.execute(query, {"call_id": call_id, "status": status})

def get_all_tickers() -> List[str]:
    """stocks 테이블에서 모든 티커 리스트를 가져옴"""
    query = text("SELECT ticker FROM stocks")
    with engine.connect() as conn:
        result = conn.execute(query)
        # 리스트 형태로 변환하여 반환
        return [row[0] for row in result]

def get_all_stocks() -> List[Dict]:
    """stocks 테이블에서 discovery에 필요한 최소 종목 정보를 가져옴"""
    query = text("SELECT ticker, company_name, ir_url FROM stocks")
    with engine.connect() as conn:
        result = conn.execute(query)
        return [dict(row._mapping) for row in result]

def update_stock_ir_url(ticker: str, ir_url: str):
    """발견한 IR 페이지 URL을 stocks 테이블에 저장"""
    query = text("""
        UPDATE stocks
        SET ir_url = :ir_url
        WHERE ticker = :ticker
    """)

    with engine.begin() as conn:
        conn.execute(query, {"ticker": ticker, "ir_url": ir_url})
    
def save_prices(price_list: List[Dict]):
    if not price_list: return

    query = text("""
        INSERT IGNORE INTO prices 
        (ticker, price_at, open_price, high_price, low_price, close_price, volume)
        VALUES (:ticker, :price_at, :open_price, :high_price, :low_price, :close_price, :volume)
    """)

    try:
        with engine.begin() as conn:
            for price in price_list:
                conn.execute(query, price)
        print(f"💾 [DB] {price_list[0]['ticker']} 주가 데이터 {len(price_list)}건 저장 완료.")
    except Exception as e:
        print(f"❌ [DB] 주가 저장 에러: {e}")

def ensure_financial_statement_items_table():
    query = text("""
        CREATE TABLE IF NOT EXISTS financial_statement_items (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            statement_type VARCHAR(32) NOT NULL,
            fiscal_period_end DATE NOT NULL,
            frequency VARCHAR(16) NOT NULL,
            line_item VARCHAR(128) NOT NULL,
            value DECIMAL(28, 4) NOT NULL,
            source VARCHAR(32) NOT NULL,
            collected_at DATETIME NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_financial_statement_items (
                ticker,
                statement_type,
                fiscal_period_end,
                frequency,
                line_item
            ),
            INDEX idx_fsi_ticker_period (ticker, fiscal_period_end),
            INDEX idx_fsi_statement_type (statement_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    with engine.begin() as conn:
        conn.execute(query)


def save_financial_statement_items(statement_items: List[Dict]):
    if not statement_items:
        return

    ensure_financial_statement_items_table()

    query = text("""
        INSERT INTO financial_statement_items
            (
                ticker,
                statement_type,
                fiscal_period_end,
                frequency,
                line_item,
                value,
                source,
                collected_at
            )
        VALUES
            (
                :ticker,
                :statement_type,
                :fiscal_period_end,
                :frequency,
                :line_item,
                :value,
                :source,
                :collected_at
            )
        ON DUPLICATE KEY UPDATE
            value = VALUES(value),
            source = VALUES(source),
            collected_at = VALUES(collected_at)
    """)

    with engine.begin() as conn:
        for item in statement_items:
            conn.execute(query, item)

    tickers = sorted({item["ticker"] for item in statement_items})
    print(f"[DB] Saved {len(statement_items)} financial statement items for {len(tickers)} tickers.")


def update_static_indicators(indicator_list: List[Dict]):
    """stocks 테이블에 52주 고점 및 평균 거래량 정보를 박제(Update)"""
    if not indicator_list: return

    query = text("""
        UPDATE stocks 
        SET high_52w = :high_52w, 
            avg_volume_20d = :avg_volume_20d 
        WHERE ticker = :ticker
    """)

    with engine.begin() as conn:
        for item in indicator_list:
            conn.execute(query, item)
    print(f"💾 [DB] {len(indicator_list)}개 종목의 정적 지표 박제 완료.")
