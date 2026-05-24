"""Redis publisher for legacy and enriched AI-engine signal messages."""

from __future__ import annotations

from collections import deque
import json
from typing import Any

try:
    from config import Settings
    from models.legacy_contract_models import LegacyPublishResult, LegacySignalMessage
except ImportError:  # pragma: no cover
    from ..config import Settings
    from ..models.legacy_contract_models import LegacyPublishResult, LegacySignalMessage

try:  # Optional at import time so local tests can run without Redis installed.
    import redis.asyncio as redis_asyncio  # type: ignore
except Exception:  # pragma: no cover
    redis_asyncio = None


class RedisSignalPublisher:
    """Publishes compatibility messages while degrading safely if Redis is unavailable."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None
        self.backup_queue: deque[dict[str, Any]] = deque(maxlen=max(1, settings.redis_backup_queue_size))

    def _get_client(self) -> Any:
        if redis_asyncio is None:
            raise RuntimeError("redis package is not installed")
        if self._client is None:
            self._client = redis_asyncio.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=self.settings.redis_socket_timeout_seconds,
                socket_timeout=self.settings.redis_socket_timeout_seconds,
            )
        return self._client

    async def _publish_json(self, channel: str, payload: dict[str, Any]) -> bool:
        client = self._get_client()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        await client.publish(channel, encoded)
        return True

    async def publish(
        self,
        *,
        legacy_signal: LegacySignalMessage,
        enriched_message: dict[str, Any] | None = None,
    ) -> LegacyPublishResult:
        legacy_payload = legacy_signal.model_dump(mode="json", exclude_none=True)
        legacy_published = False
        enriched_published = False
        errors: list[str] = []

        if self.settings.legacy_redis_publish_enabled:
            try:
                legacy_published = await self._publish_json(self.settings.redis_channel, legacy_payload)
            except Exception as exc:
                errors.append(f"legacy:{exc}")
                self.backup_queue.append({"channel": self.settings.redis_channel, "payload": legacy_payload, "error": str(exc)})

        if self.settings.redis_enriched_publish_enabled and enriched_message is not None:
            try:
                enriched_published = await self._publish_json(self.settings.redis_enriched_channel, enriched_message)
            except Exception as exc:
                errors.append(f"enriched:{exc}")
                self.backup_queue.append({"channel": self.settings.redis_enriched_channel, "payload": enriched_message, "error": str(exc)})

        return LegacyPublishResult(
            legacy_published=legacy_published,
            enriched_published=enriched_published,
            error="; ".join(errors) if errors else None,
        )


__all__ = ["RedisSignalPublisher"]
