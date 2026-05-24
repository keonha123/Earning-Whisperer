from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Mapping, Protocol


class SQLExecutor(Protocol):
    def execute_transaction(self, statements: list[tuple[str, Mapping[str, Any] | None]]) -> None: ...
    def execute_script(self, sql_script: str) -> None: ...
    def execute(self, query: str, params: Mapping[str, Any] | None = None) -> None: ...
    def fetch_one(self, query: str, params: Mapping[str, Any] | None = None) -> dict[str, Any] | None: ...
    def fetch_all(self, query: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...


@dataclass(slots=True)
class PsycopgExecutor:
    dsn: str
    connect_timeout_seconds: int = 2
    failure_cooldown_seconds: int = 15
    _cooldown_until_monotonic: float = field(default=0.0, init=False, repr=False)
    _last_connect_error: str = field(default="", init=False, repr=False)

    def _connect(self):
        now = time.monotonic()
        if now < self._cooldown_until_monotonic:
            remaining = max(0.0, self._cooldown_until_monotonic - now)
            detail = self._last_connect_error or "previous connection attempt failed"
            raise RuntimeError(f"PostgreSQL temporarily unavailable; retry suppressed for {remaining:.1f}s after the last connection failure: {detail}")
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise RuntimeError("PostgreSQL write/read access requires the psycopg package. Install it with: pip install psycopg[binary]") from exc
        try:
            return psycopg.connect(self.dsn, connect_timeout=max(1, int(self.connect_timeout_seconds)))
        except Exception as exc:
            self._last_connect_error = str(exc)
            self._cooldown_until_monotonic = time.monotonic() + max(1, int(self.failure_cooldown_seconds))
            raise

    def execute_transaction(self, statements: list[tuple[str, Mapping[str, Any] | None]]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                for query, params in statements:
                    cur.execute(query, params or {})
            conn.commit()

    def execute_script(self, sql_script: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_script)
            conn.commit()

    def execute(self, query: str, params: Mapping[str, Any] | None = None) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or {})
            conn.commit()

    def fetch_one(self, query: str, params: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise RuntimeError("PostgreSQL read access requires the psycopg package. Install it with: pip install psycopg[binary]") from exc
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params or {})
                row = cur.fetchone()
        return dict(row) if row else None

    def fetch_all(self, query: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise RuntimeError("PostgreSQL read access requires the psycopg package. Install it with: pip install psycopg[binary]") from exc
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params or {})
                rows = cur.fetchall()
        return [dict(row) for row in rows]


@dataclass(slots=True)
class BootstrapResult:
    applied: bool
    schema_path: str


__all__ = ["SQLExecutor", "PsycopgExecutor", "BootstrapResult"]
