"""Redis publisher for legacy, enriched, and investment-profile signal messages."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import time
from typing import Any

try:
    from config import Settings
    from models.intelligence_models import RedisRetryResponse
    from models.legacy_contract_models import LegacyPublishResult, LegacySignalMessage
    from services.redis_retry_spool import RedisRetrySpool
except ImportError:  # pragma: no cover
    from ..config import Settings
    from ..models.intelligence_models import RedisRetryResponse
    from ..models.legacy_contract_models import LegacyPublishResult, LegacySignalMessage
    from .redis_retry_spool import RedisRetrySpool

try:
    import redis.asyncio as redis_asyncio  # type: ignore
except Exception:  # pragma: no cover
    redis_asyncio = None


class RedisSignalPublisher:
    """Publishes compatibility messages and persists failures for later replay."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None
        self.backup_queue: deque[dict[str, Any]] = deque(maxlen=max(1, settings.redis_backup_queue_size))
        configured = Path(settings.redis_retry_spool_path)
        spool_path = configured if configured.is_absolute() else Path(__file__).resolve().parents[1] / configured
        self.retry_spool = RedisRetrySpool(spool_path, max_entries=settings.redis_retry_max_entries)

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

    def _queue_failure(self, *, channel: str, payload: dict[str, Any], error: Exception | str) -> None:
        message = str(error)
        item = {"channel": channel, "payload": payload, "error": message}
        self.backup_queue.append(item)
        self.retry_spool.append(channel=channel, payload=payload, error=message)

    async def retry_pending(self, *, limit: int | None = None) -> RedisRetryResponse:
        pending = self.retry_spool.load()
        if not pending:
            return RedisRetryResponse()
        attempt_limit = max(1, int(limit or len(pending)))
        attempted_entries = pending[:attempt_limit]
        untouched = pending[attempt_limit:]
        failed: list[dict[str, Any]] = []
        errors: list[str] = []
        published = 0
        for entry in attempted_entries:
            try:
                await self._publish_json(str(entry["channel"]), dict(entry["payload"]))
                published += 1
            except Exception as exc:
                updated = dict(entry)
                updated["attempts"] = int(updated.get("attempts") or 0) + 1
                updated["last_error"] = str(exc)
                updated["updated_at"] = int(time.time())
                failed.append(updated)
                errors.append(f"{updated.get('channel')}:{exc}")
        remaining_entries = failed + untouched
        self.retry_spool.replace(remaining_entries)
        return RedisRetryResponse(
            attempted=len(attempted_entries),
            published=published,
            remaining=len(remaining_entries),
            errors=errors,
        )

    async def publish(
        self,
        *,
        legacy_signal: LegacySignalMessage,
        enriched_message: dict[str, Any] | None = None,
    ) -> LegacyPublishResult:
        if self.settings.redis_retry_auto_flush_limit > 0 and self.retry_spool.count() > 0:
            await self.retry_pending(limit=self.settings.redis_retry_auto_flush_limit)

        legacy_payload = legacy_signal.model_dump(mode="json", exclude_none=True)
        legacy_published = False
        enriched_published = False
        profile_published = False
        retry_queued_before = self.retry_spool.count()
        errors: list[str] = []

        async def publish_channel(channel: str, payload: dict[str, Any], label: str) -> bool:
            try:
                return await self._publish_json(channel, payload)
            except Exception as exc:
                errors.append(f"{label}:{exc}")
                self._queue_failure(channel=channel, payload=payload, error=exc)
                return False

        if self.settings.legacy_redis_publish_enabled:
            legacy_published = await publish_channel(self.settings.redis_channel, legacy_payload, "legacy")

        if self.settings.redis_enriched_publish_enabled and enriched_message is not None:
            enriched_published = await publish_channel(self.settings.redis_enriched_channel, enriched_message, "enriched")

        profile_channel = self._profile_channel(legacy_signal)
        if self.settings.redis_profile_publish_enabled and profile_channel:
            profile_published = await publish_channel(profile_channel, legacy_payload, "profile")
            if self.settings.redis_enriched_publish_enabled and enriched_message is not None:
                await publish_channel(
                    f"{profile_channel}{self.settings.redis_profile_enriched_suffix}",
                    enriched_message,
                    "profile_enriched",
                )

        return LegacyPublishResult(
            legacy_published=legacy_published,
            enriched_published=enriched_published,
            profile_published=profile_published,
            profile_channel=profile_channel,
            retry_queued=max(0, self.retry_spool.count() - retry_queued_before),
            error="; ".join(errors) if errors else None,
        )

    @staticmethod
    def _profile_channel(signal: LegacySignalMessage) -> str | None:
        recommendation = signal.strategy_recommendation or {}
        hinted = recommendation.get("redis_channel_hint") if isinstance(recommendation, dict) else None
        if hinted:
            return str(hinted)
        return None


__all__ = ["RedisSignalPublisher"]
