from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_persistence_api import _FakeRepository


def test_regression_compare_and_list_endpoints() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()

    payload = {
        "strategy_code": "REVERSAL_CATALYST",
        "suite_name": "prod_guardrail_core",
        "candidate_patch_id": 1,
        "baseline": {
            "hit_rate": 0.52,
            "avg_return_bps": 18.0,
            "max_drawdown_bps": 42.0,
            "false_positive_rate": 0.14,
            "sample_size": 100,
        },
        "candidate": {
            "hit_rate": 0.57,
            "avg_return_bps": 24.0,
            "max_drawdown_bps": 36.0,
            "false_positive_rate": 0.11,
            "sample_size": 90,
        },
    }
    compare_resp = client.post("/v1/engine/regression/compare", json=payload)
    assert compare_resp.status_code == 200
    assert compare_resp.json()["result"]["verdict"] == "pass"

    list_resp = client.get("/v1/engine/regression/reports?strategy_code=REVERSAL_CATALYST")
    assert list_resp.status_code == 200
    assert list_resp.json()["result"]["items"][0]["strategy_code"] == "REVERSAL_CATALYST"
