from __future__ import annotations

import sys
from types import SimpleNamespace

from db.postgres_executor import PsycopgExecutor


def test_psycopg_executor_passes_connect_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_connect(dsn, **kwargs):
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return "connection"

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=_fake_connect))

    executor = PsycopgExecutor(dsn="postgresql://example", connect_timeout_seconds=2)
    connection = executor._connect()

    assert connection == "connection"
    assert captured["dsn"] == "postgresql://example"
    assert captured["kwargs"] == {"connect_timeout": 2}


def test_psycopg_executor_enters_failure_cooldown(monkeypatch) -> None:
    captured = {"calls": 0}

    def _failing_connect(dsn, **kwargs):
        captured["calls"] += 1
        raise RuntimeError("database down")

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=_failing_connect))

    executor = PsycopgExecutor(dsn="postgresql://example", connect_timeout_seconds=2, failure_cooldown_seconds=15)

    try:
        executor._connect()
    except RuntimeError as exc:
        assert "database down" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("first connection attempt should fail")

    try:
        executor._connect()
    except RuntimeError as exc:
        assert "temporarily unavailable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("second connection attempt should fast-fail during cooldown")

    assert captured["calls"] == 1
