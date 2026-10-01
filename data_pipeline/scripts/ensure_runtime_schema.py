"""Apply and verify data_pipeline tables on an existing MySQL volume.

Usage:
    python -m data_pipeline.scripts.ensure_runtime_schema
    python -m data_pipeline.scripts.ensure_runtime_schema --check-only
"""

from __future__ import annotations

import argparse
import json
from typing import Iterable

from sqlalchemy import text

from data_pipeline import database


SCHEMA_BUILDERS = (
    database.ensure_schedule_time_schema,
    database.ensure_transcript_archive_schema,
    database.ensure_transcript_outbox_schema,
    database.ensure_webcast_recipe_schema,
    database.ensure_webcast_learning_target_schema,
    database.ensure_webcast_training_surface_schema,
    database.ensure_webcast_replay_target_schema,
    database.ensure_webcast_replay_discovery_schema,
)

REQUIRED_COLUMNS = {
    "calls": tuple(database.SCHEDULE_TIME_COLUMNS),
    "transcript_segments": (
        "call_id", "ticker", "sequence_no", "start_ms", "end_ms", "text_chunk",
        "session_end_reason", "session_success_eligible", "target_identity_verified",
    ),
    "transcript_outbox": (
        "delivery_key", "call_id", "ticker", "sequence_no", "destination",
        "payload_json", "status", "attempt_count", "next_attempt_at",
    ),
}


def _table_columns(table: str) -> set[str]:
    with database.engine.connect() as conn:
        return {str(row[0]) for row in conn.execute(text(f"SHOW COLUMNS FROM `{table}`"))}


def inspect_schema() -> dict[str, object]:
    """Return missing tables/columns without changing the database."""
    tables: dict[str, dict[str, object]] = {}
    with database.engine.connect() as conn:
        existing_tables = {
            str(row[0])
            for row in conn.execute(
                text("SELECT TABLE_NAME FROM information_schema.tables WHERE table_schema = DATABASE()")
            )
        }
    for table, required in REQUIRED_COLUMNS.items():
        missing_table = table not in existing_tables
        columns = set() if missing_table else _table_columns(table)
        tables[table] = {
            "present": not missing_table,
            "missing_columns": sorted(set(required) - columns),
        }
    missing_tables = sorted(table for table, value in tables.items() if not value["present"])
    missing_columns = {
        table: value["missing_columns"]
        for table, value in tables.items()
        if value["missing_columns"]
    }
    return {
        "database": database.engine.url.database,
        "tables": tables,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "ready": not missing_tables and not missing_columns,
    }


def apply_schema() -> None:
    for builder in SCHEMA_BUILDERS:
        builder()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply/verify data_pipeline MySQL runtime schema.")
    parser.add_argument("--check-only", action="store_true", help="Do not mutate the database.")
    parser.add_argument("--json", action="store_true", help="Print the inspection as JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.check_only:
        apply_schema()
    result = inspect_schema()
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        print(f"database={result['database']} ready={result['ready']}")
        if result["missing_tables"]:
            print(f"missing_tables={','.join(result['missing_tables'])}")
        if result["missing_columns"]:
            print(f"missing_columns={result['missing_columns']}")
        if result["ready"]:
            print("DATA_PIPELINE_SCHEMA_READY")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
