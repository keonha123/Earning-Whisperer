from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from main import create_app


class _ReadyExecutor:
    def fetch_one(self, query):
        return {"ok": 1}


class _BrokenExecutor:
    def fetch_one(self, query):
        raise RuntimeError("database offline")


def test_health_ready_requires_gemini_key() -> None:
    app = create_app()
    app.state.settings = SimpleNamespace(
        gemini_api_key="",
        gemini_primary_model="gemini-3.1-flash-preview",
        gemini_review_model="gemini-3.1-pro-preview",
    )
    app.state.event_store_repository = SimpleNamespace(executor=_ReadyExecutor())

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["checks"]["gemini_api_key"] == "missing"
    assert "GEMINI_API_KEY is not configured" in payload["detail"]


def test_health_ready_reports_database_errors() -> None:
    app = create_app()
    app.state.settings = SimpleNamespace(
        gemini_api_key="configured",
        gemini_primary_model="gemini-3.1-flash-preview",
        gemini_review_model="gemini-3.1-pro-preview",
    )
    app.state.event_store_repository = SimpleNamespace(executor=_BrokenExecutor())

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["checks"]["database"] == "error"
    assert "database offline" in payload["detail"]


def test_health_ready_succeeds_when_key_and_database_are_ready() -> None:
    app = create_app()
    app.state.settings = SimpleNamespace(
        gemini_api_key="configured",
        gemini_primary_model="gemini-3.1-flash-preview",
        gemini_review_model="gemini-3.1-pro-preview",
    )
    app.state.event_store_repository = SimpleNamespace(executor=_ReadyExecutor())

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["gemini_api_key"] == "configured"
    assert payload["checks"]["database"] == "ready"
    assert payload["detail"] == "ready"
