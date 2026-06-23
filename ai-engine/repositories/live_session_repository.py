"""Durable live-session storage with atomic JSON and optional PostgreSQL mirroring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any

try:
    from db.postgres_executor import SQLExecutor
    from models.live_session_models import LiveEarningsSessionState, LiveSessionStatus, LiveSessionSummary
except ImportError:  # pragma: no cover
    from ..db.postgres_executor import SQLExecutor
    from ..models.live_session_models import LiveEarningsSessionState, LiveSessionStatus, LiveSessionSummary


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class LiveSessionRepository:
    def __init__(
        self,
        *,
        store_path: str | Path,
        executor: SQLExecutor | None = None,
        retention_hours: int = 168,
        max_sessions: int = 500,
    ) -> None:
        self.store_path = Path(store_path)
        self.executor = executor
        self.retention_hours = max(1, int(retention_hours))
        self.max_sessions = max(1, int(max_sessions))
        self._lock = threading.RLock()

    @property
    def backend_name(self) -> str:
        return "postgres+json" if self.executor is not None else "json"

    def save(self, state: LiveEarningsSessionState) -> LiveEarningsSessionState:
        self._validate_session_id(state.session_id)
        payload = state.model_dump(mode="json")
        with self._lock:
            self.store_path.mkdir(parents=True, exist_ok=True)
            target = self._session_path(state.session_id)
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
            self._prune_local_locked()
        self._mirror_postgres(payload)
        return state

    def get(self, session_id: str) -> LiveEarningsSessionState | None:
        self._validate_session_id(session_id)
        target = self._session_path(session_id)
        if target.exists():
            try:
                return LiveEarningsSessionState.model_validate_json(target.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                pass
        payload = self._fetch_postgres(session_id)
        if payload is None:
            return None
        state = LiveEarningsSessionState.model_validate(payload)
        try:
            self.save(state)
        except OSError:
            pass
        return state

    def list(
        self,
        *,
        ticker: str | None = None,
        status: LiveSessionStatus | None = None,
        limit: int = 50,
    ) -> list[LiveSessionSummary]:
        normalized_ticker = ticker.upper().strip() if ticker else None
        summaries: list[LiveSessionSummary] = []
        if self.store_path.exists():
            paths = sorted(self.store_path.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
            for path in paths:
                if len(summaries) >= max(1, limit):
                    break
                try:
                    state = LiveEarningsSessionState.model_validate_json(path.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    continue
                if normalized_ticker and state.ticker != normalized_ticker:
                    continue
                if status is not None and state.status != status:
                    continue
                summaries.append(self._summary(state))
        if summaries or self.executor is None:
            return summaries
        return self._list_postgres(ticker=normalized_ticker, status=status, limit=limit)

    def _session_path(self, session_id: str) -> Path:
        return self.store_path / f"{session_id}.json"

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not _SAFE_ID.fullmatch(str(session_id or "")):
            raise ValueError("Invalid live-session id.")

    def _prune_local_locked(self) -> None:
        paths = sorted(self.store_path.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.retention_hours)
        for index, path in enumerate(paths):
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if index >= self.max_sessions or modified < cutoff:
                try:
                    path.unlink()
                except OSError:
                    continue

    def _mirror_postgres(self, payload: dict[str, Any]) -> None:
        if self.executor is None:
            return
        try:
            self.executor.execute(
                """
                insert into ai_live_earnings_sessions
                    (session_id, ticker, status, started_at, updated_at, completed_at, payload_json)
                values
                    (%(session_id)s, %(ticker)s, %(status)s, %(started_at)s, %(updated_at)s, %(completed_at)s, %(payload_json)s::jsonb)
                on conflict (session_id) do update set
                    ticker = excluded.ticker,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at,
                    payload_json = excluded.payload_json
                """,
                {
                    "session_id": payload["session_id"],
                    "ticker": payload["ticker"],
                    "status": payload["status"],
                    "started_at": payload["started_at"],
                    "updated_at": payload["updated_at"],
                    "completed_at": payload.get("completed_at"),
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                },
            )
        except Exception:
            return

    def _fetch_postgres(self, session_id: str) -> dict[str, Any] | None:
        if self.executor is None:
            return None
        try:
            row = self.executor.fetch_one(
                "select payload_json from ai_live_earnings_sessions where session_id = %(session_id)s",
                {"session_id": session_id},
            )
        except Exception:
            return None
        if not row:
            return None
        return self._decode_payload(row.get("payload_json"))

    def _list_postgres(
        self,
        *,
        ticker: str | None,
        status: LiveSessionStatus | None,
        limit: int,
    ) -> list[LiveSessionSummary]:
        if self.executor is None:
            return []
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 200))}
        if ticker:
            clauses.append("ticker = %(ticker)s")
            params["ticker"] = ticker
        if status is not None:
            clauses.append("status = %(status)s")
            params["status"] = status.value
        where = f"where {' and '.join(clauses)}" if clauses else ""
        try:
            rows = self.executor.fetch_all(
                f"select payload_json from ai_live_earnings_sessions {where} order by updated_at desc limit %(limit)s",
                params,
            )
        except Exception:
            return []
        summaries: list[LiveSessionSummary] = []
        for row in rows:
            try:
                state = LiveEarningsSessionState.model_validate(self._decode_payload(row.get("payload_json")))
            except (TypeError, ValueError):
                continue
            summaries.append(self._summary(state))
        return summaries

    @staticmethod
    def _decode_payload(payload: Any) -> dict[str, Any]:
        if isinstance(payload, str):
            return json.loads(payload)
        return dict(payload or {})

    @staticmethod
    def _summary(state: LiveEarningsSessionState) -> LiveSessionSummary:
        return LiveSessionSummary(
            session_id=state.session_id,
            ticker=state.ticker,
            call_title=state.call_title,
            fiscal_period=state.fiscal_period,
            status=state.status,
            started_at=state.started_at,
            updated_at=state.updated_at,
            completed_at=state.completed_at,
            chunk_count=len(state.timeline),
            fact_checks_processed=state.fact_check_progress.processed,
            final_action=state.final_signal.action if state.final_signal else None,
            ai_score=state.final_signal.ai_score if state.final_signal else state.scorecard.overall,
        )


__all__ = ["LiveSessionRepository"]
