"""Durable company relationship, executive, and speaker metadata repository."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

try:
    from db.postgres_executor import SQLExecutor
    from models.intelligence_models import ExecutiveProfile, ImpactRelationshipRecord, SpeakerMetadata
except ImportError:  # pragma: no cover
    from ..db.postgres_executor import SQLExecutor
    from ..models.intelligence_models import ExecutiveProfile, ImpactRelationshipRecord, SpeakerMetadata


class CompanyIntelligenceRepository:
    def __init__(
        self,
        *,
        store_path: str | Path,
        executor: SQLExecutor | None = None,
        schema_path: str | Path | None = None,
        seed_path: str | Path | None = None,
    ) -> None:
        self.store_path = Path(store_path)
        self.seed_path = Path(seed_path) if seed_path else None
        self.executor = executor
        self.schema_path = Path(schema_path) if schema_path else None
        self._lock = threading.RLock()
        self._data = self._load_file()

    @property
    def backend_name(self) -> str:
        return "postgres+json" if self.executor is not None else "json"

    def bootstrap_schema(self) -> None:
        if self.executor is None or self.schema_path is None:
            return
        self.executor.execute_script(self.schema_path.read_text(encoding="utf-8"))

    def get_relationships(self, source_ticker: str) -> list[ImpactRelationshipRecord]:
        ticker = source_ticker.upper()
        rows = self._fetch_postgres_relationships(ticker)
        if rows:
            return [self._relationship_from_row(row) for row in rows]
        return [
            ImpactRelationshipRecord.model_validate(item)
            for item in self._data.get("relationships", [])
            if str(item.get("source_ticker", "")).upper() == ticker
        ]

    def get_executives(self, ticker: str) -> list[ExecutiveProfile]:
        normalized = ticker.upper()
        rows = self._fetch_postgres_records("ai_executive_profiles", normalized)
        if rows:
            return [ExecutiveProfile.model_validate(self._decode_payload(row)) for row in rows]
        return [
            ExecutiveProfile.model_validate(item)
            for item in self._data.get("executives", [])
            if str(item.get("ticker", "")).upper() == normalized
        ]

    def get_speakers(self, ticker: str) -> list[SpeakerMetadata]:
        normalized = ticker.upper()
        rows = self._fetch_postgres_records("ai_speaker_metadata", normalized)
        if rows:
            return [SpeakerMetadata.model_validate(self._decode_payload(row)) for row in rows]
        return [
            SpeakerMetadata.model_validate(item)
            for item in self._data.get("speakers", [])
            if str(item.get("ticker", "")).upper() == normalized
        ]

    def upsert_relationships(self, relationships: list[ImpactRelationshipRecord]) -> int:
        if not relationships:
            return 0
        with self._lock:
            current = {
                self._relationship_key(ImpactRelationshipRecord.model_validate(item)): item
                for item in self._data.get("relationships", [])
            }
            for relationship in relationships:
                current[self._relationship_key(relationship)] = relationship.model_dump(mode="json")
            self._data["relationships"] = list(current.values())
            self._write_file()
        self._persist_relationships(relationships)
        return len(relationships)

    def upsert_executives(self, executives: list[ExecutiveProfile]) -> int:
        return self._upsert_payload_records("executives", executives, "executive_id", "ai_executive_profiles")

    def upsert_speakers(self, speakers: list[SpeakerMetadata]) -> int:
        return self._upsert_payload_records("speakers", speakers, "speaker_id", "ai_speaker_metadata")

    def _upsert_payload_records(self, key: str, records: list[Any], id_field: str, table: str) -> int:
        if not records:
            return 0
        with self._lock:
            current = {str(item.get(id_field)): item for item in self._data.get(key, [])}
            for record in records:
                current[str(getattr(record, id_field))] = record.model_dump(mode="json")
            self._data[key] = list(current.values())
            self._write_file()
        if self.executor is not None:
            statements = []
            for record in records:
                payload = record.model_dump(mode="json")
                statements.append(
                    (
                        f"""
                        insert into {table} (record_id, ticker, payload_json, updated_at)
                        values (%(record_id)s, %(ticker)s, %(payload_json)s::jsonb, now())
                        on conflict (record_id) do update set
                            ticker = excluded.ticker,
                            payload_json = excluded.payload_json,
                            updated_at = now()
                        """,
                        {
                            "record_id": str(payload[id_field]),
                            "ticker": str(payload["ticker"]).upper(),
                            "payload_json": json.dumps(payload, ensure_ascii=False),
                        },
                    )
                )
            self._execute_fail_open(statements)
        return len(records)

    def _persist_relationships(self, relationships: list[ImpactRelationshipRecord]) -> None:
        if self.executor is None:
            return
        statements = []
        for item in relationships:
            payload = item.model_dump(mode="json")
            statements.append(
                (
                    """
                    insert into ai_company_impact_relationships
                        (source_ticker, target_ticker, relationship, strength, payload_json, updated_at)
                    values
                        (%(source_ticker)s, %(target_ticker)s, %(relationship)s, %(strength)s, %(payload_json)s::jsonb, now())
                    on conflict (source_ticker, target_ticker, relationship) do update set
                        strength = excluded.strength,
                        payload_json = excluded.payload_json,
                        updated_at = now()
                    """,
                    {
                        "source_ticker": item.source_ticker.upper(),
                        "target_ticker": item.target_ticker.upper(),
                        "relationship": item.relationship,
                        "strength": item.strength,
                        "payload_json": json.dumps(payload, ensure_ascii=False),
                    },
                )
            )
        self._execute_fail_open(statements)

    def _fetch_postgres_relationships(self, ticker: str) -> list[dict[str, Any]]:
        if self.executor is None:
            return []
        try:
            return self.executor.fetch_all(
                """
                select payload_json
                from ai_company_impact_relationships
                where source_ticker = %(ticker)s
                order by strength desc, target_ticker asc
                """,
                {"ticker": ticker},
            )
        except Exception:
            return []

    def _fetch_postgres_records(self, table: str, ticker: str) -> list[dict[str, Any]]:
        if self.executor is None:
            return []
        try:
            return self.executor.fetch_all(
                f"select payload_json from {table} where ticker = %(ticker)s order by updated_at desc",
                {"ticker": ticker},
            )
        except Exception:
            return []

    def _execute_fail_open(self, statements: list[tuple[str, dict[str, Any]]]) -> None:
        if self.executor is None or not statements:
            return
        try:
            self.executor.execute_transaction(statements)
        except Exception:
            return

    def _load_file(self) -> dict[str, list[dict[str, Any]]]:
        source_path = self.store_path if self.store_path.exists() else self.seed_path
        if source_path is None or not source_path.exists():
            return {"relationships": [], "executives": [], "speakers": []}
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {"relationships": [], "executives": [], "speakers": []}
        return {
            "relationships": list(payload.get("relationships") or []),
            "executives": list(payload.get("executives") or []),
            "speakers": list(payload.get("speakers") or []),
        }

    def _write_file(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.store_path)

    @staticmethod
    def _relationship_key(item: ImpactRelationshipRecord) -> str:
        return "|".join([item.source_ticker.upper(), item.target_ticker.upper(), item.relationship.lower()])

    @staticmethod
    def _decode_payload(row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload_json", row)
        if isinstance(payload, str):
            return json.loads(payload)
        return dict(payload or {})

    @classmethod
    def _relationship_from_row(cls, row: dict[str, Any]) -> ImpactRelationshipRecord:
        return ImpactRelationshipRecord.model_validate(cls._decode_payload(row))


__all__ = ["CompanyIntelligenceRepository"]
