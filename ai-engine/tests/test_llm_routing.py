from __future__ import annotations

from fastapi.testclient import TestClient

from main import create_app


def test_health_and_stats_expose_current_models() -> None:
    app = create_app()
    with TestClient(app) as client:
        health = client.get('/health')
        stats = client.get('/stats')

    assert health.status_code == 200
    assert stats.status_code == 200

    health_data = health.json()
    stats_data = stats.json()

    assert health_data['status'] == 'ok'
    assert health_data['primary_model'] == 'gemini-3.1-flash-lite'
    assert health_data['review_model'] == 'gemini-3.1-pro-preview'
    assert stats_data['models']['fast'] == 'gemini-3.1-flash-lite'
    assert stats_data['models']['review'] == 'gemini-3.1-pro-preview'
