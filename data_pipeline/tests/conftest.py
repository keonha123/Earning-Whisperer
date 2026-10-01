from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_operation_artifacts(monkeypatch, tmp_path):
    """Keep test health events out of the production operations audit trail."""
    operations_dir = tmp_path / "operations"
    monkeypatch.setenv("OPERATIONS_LOG_DIR", str(operations_dir))
    monkeypatch.setenv(
        "OPERATIONS_ALERT_STATE_FILE",
        str(operations_dir / "alerts-state.json"),
    )

