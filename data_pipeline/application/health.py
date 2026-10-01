"""Shared, rate-limited health reporting for all application services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from .settings import env_int


class RuntimeHealth:
    def __init__(self):
        self._database_outage_active = False
        self._database_outage_last_logged_at: datetime | None = None

    @staticmethod
    def record_event(event_type: str, **payload: Any) -> None:
        from ..operations import record_event
        try:
            record_event(event_type, **payload)
        except Exception as exc:
            print(f"[OperationsLog] write skipped: {str(exc)[:160]}")


    def database_unavailable(self, operation: str, exc: BaseException) -> None:
        """Expose a paused watcher state without flooding logs during an outage."""
        now = datetime.now(timezone.utc)
        interval_seconds = env_int(
            "DATE_STREAM_DB_OUTAGE_LOG_INTERVAL_SECONDS",
            300,
            30,
        )
        should_log = (
            not self._database_outage_active
            or self._database_outage_last_logged_at is None
            or (now - self._database_outage_last_logged_at).total_seconds()
            >= interval_seconds
        )
        self._database_outage_active = True
        if not should_log:
            return
        self._database_outage_last_logged_at = now
        self.record_event(
            "database_unavailable",
            status="paused",
            operation=operation,
            error=str(exc),
            retry_after_seconds=interval_seconds,
        )
        print(
            f"[Database] unavailable during {operation}; watcher is paused and will retry: {exc}",
            flush=True,
        )


    def database_recovered(self, operation: str) -> None:
        """Record the first successful database operation after an outage."""
        if not self._database_outage_active:
            return
        self._database_outage_active = False
        self._database_outage_last_logged_at = None
        self.record_event("database_recovered", status="resumed", operation=operation)
        print(f"[Database] recovered during {operation}; watcher resumed", flush=True)
