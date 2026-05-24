from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_persistence_api import _FakeRepository, _fake_run_analysis


class _SuppressingRepository(_FakeRepository):
    def get_effective_control_states(self, **kwargs):
        return [{"control_type": "signal_suppress", "enabled": True, "scope_type": "global"}]


def test_gate_patch_approve_and_audit_endpoints() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()

    approve_resp = client.post("/v1/engine/controls/gate-patches/1/approve", json={"actor": "pm"})
    assert approve_resp.status_code == 200
    assert approve_resp.json()["result"]["approval_state"] == "approved"

    audit_resp = client.get("/v1/engine/controls/gate-patches/1/audit")
    assert audit_resp.status_code == 200
    assert audit_resp.json()["result"]["audit_trail_count"] >= 1


def test_rollout_and_emergency_endpoints() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()

    rollout_resp = client.post("/v1/engine/controls/gate-patches/1/rollouts", json={"actor": "pm", "report_id": "report_demo"})
    assert rollout_resp.status_code == 200
    assert rollout_resp.json()["result"]["status"] == "canary_active"

    emergency_resp = client.post("/v1/engine/controls/emergency-state", json={"control_type": "promotion_freeze", "enabled": True, "scope_type": "global", "actor": "pm"})
    assert emergency_resp.status_code == 200
    assert emergency_resp.json()["result"]["control_type"] == "promotion_freeze"


def test_analyze_response_adds_control_fields_when_suppressed(monkeypatch) -> None:
    monkeypatch.setattr(main.app.state.analysis_service, "analyze", _fake_run_analysis)
    client = TestClient(main.app)
    main.app.state.event_store_repository = _SuppressingRepository()

    resp = client.post(
        "/v1/engine/analyze",
        json={
            "ticker": "TSLA",
            "prompt": "Guidance commentary was mixed.",
            "section_type": "Q_AND_A",
            "source_type": "EARNINGS_CALL",
            "chunk_sequence": 1,
            "market_data": {"current_price": 100.0, "gap_pct": 1.0, "surprise_pct": 3.0, "volume_ratio": 1.8},
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["analysis"]["execution_allowed"] is False
    assert payload["analysis"]["decision_state"] == "suppressed"
    assert payload["analysis"]["blocked_reason_ko"]
