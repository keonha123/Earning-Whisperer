"""Runtime schema upgrades for existing volumes."""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from . import connection


SCHEDULE_TIME_COLUMNS = {
    "schedule_revision": "INT NOT NULL DEFAULT 0",
    "schedule_observed_at": "DATETIME(6) NULL",
    "verified_fiscal_year": "INT NULL",
    "verified_fiscal_quarter": "VARCHAR(8) NULL",
    "official_event_key": "VARCHAR(2048) NULL",
    "official_event_identity": "TEXT NULL",
    "schedule_superseded_by": "BIGINT NULL",
    "webcast_date": "DATE NULL",
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
    "stream_probe_retry_not_before": "DATETIME NULL",
    "stream_probe_retry_reason": "VARCHAR(64) NULL",
    "stream_detected_at": "DATETIME NULL",
    "stream_probe_lease_owner": "VARCHAR(128) NULL",
    "stream_probe_lease_until": "DATETIME NULL",
    "stream_probe_heartbeat_at": "DATETIME NULL",
    "capture_attempts": "INT NOT NULL DEFAULT 0",
    "capture_previous_status": "VARCHAR(32) NULL",
    "capture_lease_owner": "VARCHAR(128) NULL",
    "capture_lease_until": "DATETIME NULL",
    "capture_started_at": "DATETIME NULL",
    "capture_heartbeat_at": "DATETIME NULL",
    "capture_manifest_path": "VARCHAR(2048) NULL",
    "capture_session_id": "VARCHAR(128) NULL",
    "capture_retry_not_before": "DATETIME NULL",
    "capture_last_error": "TEXT NULL",
    "schedule_refresh_requested_at": "DATETIME NULL",
    "schedule_refresh_attempts": "INT NOT NULL DEFAULT 0",
    "schedule_refresh_last_error": "TEXT NULL",
    "schedule_revalidation_status": "VARCHAR(32) NOT NULL DEFAULT 'clear'",
    "schedule_revalidation_reason": "VARCHAR(64) NULL",
    "schedule_last_yahoo_seen_at": "DATETIME NULL",
    "schedule_last_nasdaq_seen_at": "DATETIME NULL",
    "schedule_revalidation_evidence": "TEXT NULL",
    "schedule_enrichment_last_attempt_at": "DATETIME NULL",
    "schedule_enrichment_retry_not_before": "DATETIME NULL",
    "schedule_enrichment_failure_kind": "VARCHAR(64) NULL",
    "schedule_enrichment_last_error": "TEXT NULL",
    "schedule_discovery_fingerprint": "CHAR(64) NULL",
    "schedule_discovery_checked_at": "DATETIME NULL",
    "schedule_discovery_changed_at": "DATETIME NULL",
}

TRANSCRIPT_SESSION_COLUMNS = {
    "session_end_reason": "VARCHAR(64) NULL",
    "session_success_eligible": "BOOLEAN NOT NULL DEFAULT FALSE",
    "target_identity_verified": "BOOLEAN NOT NULL DEFAULT FALSE",
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
            session_end_reason VARCHAR(64) NULL,
            session_success_eligible BOOLEAN NOT NULL DEFAULT FALSE,
            target_identity_verified BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_transcript_segments_call_sequence (call_id, sequence_no),
            INDEX idx_transcript_segments_ticker_created (ticker, created_at),
            INDEX idx_transcript_segments_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with connection.engine.begin() as conn:
        conn.execute(query)
        existing_columns = {
            row[0]
            for row in conn.execute(text("SHOW COLUMNS FROM transcript_segments"))
        }
        for column, definition in TRANSCRIPT_SESSION_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE transcript_segments "
                        f"ADD COLUMN {column} {definition}"
                    )
                )


def ensure_transcript_outbox_schema() -> None:
    """Create the durable downstream delivery queue on existing DB volumes."""
    query = text("""
        CREATE TABLE IF NOT EXISTS transcript_outbox (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            delivery_key CHAR(64) NOT NULL,
            call_id VARCHAR(128) NOT NULL,
            ticker VARCHAR(20) NOT NULL,
            sequence_no INT NOT NULL,
            destination VARCHAR(32) NOT NULL,
            payload_json LONGTEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            attempt_count INT NOT NULL DEFAULT 0,
            next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT NULL,
            sent_at DATETIME NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_transcript_outbox_delivery_key (delivery_key),
            UNIQUE KEY uk_transcript_outbox_destination_sequence (call_id, destination, sequence_no),
            INDEX idx_transcript_outbox_pending (status, next_attempt_at),
            INDEX idx_transcript_outbox_call (call_id, sequence_no)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with connection.engine.begin() as conn:
        conn.execute(query)


def _execute_schedule_ddl(conn, statement: str, *, duplicate_code: int,
                          object_name: str, object_kind: str) -> None:
    """Another startup worker may create the same column/index after our read.

    Accept only MySQL's expected duplicate error and confirm that the object
    now exists. Permission, connection, syntax, and other DDL failures remain
    visible to the caller; no broad exception suppression is used.
    """
    try:
        conn.execute(text(statement))
    except OperationalError as error:
        if not error.orig.args or error.orig.args[0] != duplicate_code:
            raise
        if object_kind == "column":
            exists = any(row[0] == object_name for row in conn.execute(text("SHOW COLUMNS FROM calls")))
        else:
            exists = any(row[2] == object_name for row in conn.execute(text("SHOW INDEX FROM calls")))
        if not exists:
            raise


def ensure_schedule_time_schema() -> None:
    """Add schedule-verification fields to existing local MySQL volumes."""
    with connection.engine.begin() as conn:
        existing_columns = {
            row[0]
            for row in conn.execute(text("SHOW COLUMNS FROM calls"))
        }
        for column, definition in SCHEDULE_TIME_COLUMNS.items():
            if column not in existing_columns:
                _execute_schedule_ddl(
                    conn, f"ALTER TABLE calls ADD COLUMN {column} {definition}",
                    duplicate_code=1060, object_name=column, object_kind="column",
                )

        indexes = {
            row[2]
            for row in conn.execute(text("SHOW INDEX FROM calls"))
        }
        required_indexes = {
            "idx_calls_status_scheduled_at_utc": "status, scheduled_at_utc",
            "idx_calls_status_webcast_date": "status, webcast_date",
            "idx_calls_stream_probe": "status, earning_at, last_stream_probe_at",
            "idx_calls_probe_lease": "stream_probe_status, stream_probe_lease_until",
            "idx_calls_capture_lease": "status, capture_lease_until",
            "idx_calls_capture_retry": "status, capture_retry_not_before",
            "idx_calls_probe_retry": "status, stream_probe_retry_not_before",
            "idx_calls_schedule_revalidation": "status, schedule_revalidation_status, earning_at",
            "idx_calls_schedule_enrichment_retry": "status, schedule_enrichment_retry_not_before, earning_at",
        }
        for name, columns in required_indexes.items():
            if name not in indexes:
                _execute_schedule_ddl(
                    conn, f"CREATE INDEX {name} ON calls ({columns})",
                    duplicate_code=1061, object_name=name, object_kind="index",
                )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schedule_enrichment_circuits (
                    scope VARCHAR(64) NOT NULL PRIMARY KEY,
                    state VARCHAR(16) NOT NULL DEFAULT 'closed',
                    failure_kind VARCHAR(64) NULL,
                    failure_count INT NOT NULL DEFAULT 0,
                    opened_at DATETIME NULL,
                    retry_not_before DATETIME NULL,
                    last_error TEXT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_schedule_enrichment_circuits_retry (state, retry_not_before)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_change_history (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                call_id BIGINT NOT NULL,
                revision INT NOT NULL,
                reason VARCHAR(64) NOT NULL,
                observed_at DATETIME(6) NOT NULL,
                before_json LONGTEXT NOT NULL,
                after_json LONGTEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_schedule_history_call (call_id, revision)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))

        # Older reconciliation code hard-quarantined disagreements between two
        # broad third-party calendars. Those rows are safe to watch with a
        # wider date window; only issuer-page conflicts remain hard exclusions.
        conn.execute(
            text(
                """
                UPDATE calls
                SET schedule_revalidation_status = 'provisional_watch'
                WHERE schedule_revalidation_status = 'required'
                  AND schedule_revalidation_reason IN (
                      'date_mismatch', 'yahoo_source_missing', 'nasdaq_only',
                      'yahoo_date_changed'
                  )
                """
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
    with connection.engine.begin() as conn:
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
    with connection.engine.begin() as conn:
        conn.execute(query)


def ensure_webcast_training_surface_schema() -> None:
    """Create a ticker-level audit for replay/proxy registration-to-audio coverage."""
    query = text("""
        CREATE TABLE IF NOT EXISTS webcast_training_surface_audits (
            ticker VARCHAR(20) PRIMARY KEY,
            ir_url VARCHAR(2048) NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            surface_kind VARCHAR(32) NOT NULL DEFAULT 'unknown',
            selected_url VARCHAR(2048) NULL,
            attempt_count INT NOT NULL DEFAULT 0,
            audible_count INT NOT NULL DEFAULT 0,
            last_attempt_at DATETIME NULL,
            last_audible_at DATETIME NULL,
            last_error TEXT NULL,
            last_output TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_training_surface_status (status, last_attempt_at),
            INDEX idx_training_surface_kind (surface_kind, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with connection.engine.begin() as conn:
        conn.execute(query)


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
    with connection.engine.begin() as conn:
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
    with connection.engine.begin() as conn:
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

    with connection.engine.begin() as conn:
        conn.execute(query)
