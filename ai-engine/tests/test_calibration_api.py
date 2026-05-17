from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_persistence_api import _FakeRepository


def test_calibration_run_and_promote_endpoints() -> None:
    client = TestClient(main.app)
    main.app.state.event_store_repository = _FakeRepository()

    run_resp = client.post("/v1/engine/calibration/run", json={"strategy_code": "REVERSAL_CATALYST", "actor": "pm"})
    assert run_resp.status_code == 200
    assert run_resp.json()["result"]["learning_mode"] == "patch proposal"

    list_resp = client.get("/v1/engine/calibration/proposals?strategy_code=REVERSAL_CATALYST")
    assert list_resp.status_code == 200
    assert list_resp.json()["result"]["items"][0]["strategy_code"] == "REVERSAL_CATALYST"

    promote_resp = client.post("/v1/engine/calibration/proposals/1/promote", json={"actor": "pm"})
    assert promote_resp.status_code == 200
    assert promote_resp.json()["result"]["status"] == "promotion_ready"
