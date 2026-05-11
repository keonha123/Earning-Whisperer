from __future__ import annotations

import httpx


class AiEngineNewsClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def ingest_news(self, items: list[dict]) -> dict:
        if not items:
            return {"status": "skipped", "accepted_count": 0}

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/api/v1/integration/collector/news",
                json={"items": items},
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"status": "accepted"}
