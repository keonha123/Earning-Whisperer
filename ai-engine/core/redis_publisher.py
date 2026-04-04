"""Redis publisher that preserves the backend contract while optionally emitting enriched signals."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Deque, Optional

import redis.asyncio as aioredis

from ..config import get_settings
from ..models.contract_models import BackendRedisSignal
from ..models.signal_models import TradingSignalV3

logger = logging.getLogger(__name__)


class RedisPublisher:
    """Publish the minimal backend contract and an optional enriched side-channel."""

    def __init__(self) -> None:
        settings = get_settings()
        self._url = settings.redis_url
        self._channel = settings.redis_channel
        self._enriched_channel = settings.redis_enriched_channel
        self._backup_max = settings.redis_backup_queue_size
        self._reconnect_delay = settings.redis_reconnect_delay

        self._client: Optional[aioredis.Redis] = None
        self._connected = False
        self._primary_backup_queue: Deque[str] = deque(maxlen=self._backup_max)
        self._enriched_backup_queue: Deque[str] = deque(maxlen=self._backup_max)
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        try:
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            await self._client.ping()
            self._connected = True
            logger.info("Redis connected: %s", self._url)
        except Exception as exc:  # pragma: no cover - environment dependent
            self._connected = False
            logger.error("Initial Redis connection failed: %s", exc)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._connected = False
            logger.info("Redis disconnected")

    async def publish(
        self,
        signal: TradingSignalV3,
        *,
        backend_signal: BackendRedisSignal,
    ) -> bool:
        """Publish the backend contract and keep the enriched payload on a side-channel."""

        primary_payload = backend_signal.model_dump_json(exclude_none=True)
        enriched_payload = (
            signal.model_dump_json(exclude_none=True)
            if self._enriched_channel
            else None
        )

        async with self._lock:
            if not self._connected:
                await self._try_reconnect()

            if self._connected and self._client is not None:
                try:
                    await self._flush_backup_queues()
                    await self._client.publish(self._channel, primary_payload)
                    if self._enriched_channel and enriched_payload is not None:
                        await self._client.publish(self._enriched_channel, enriched_payload)
                    logger.debug("Redis publish succeeded: ticker=%s", signal.ticker)
                    return True
                except Exception as exc:  # pragma: no cover - network dependent
                    logger.error("Redis publish failed: %s", exc)
                    self._connected = False

            self._queue_primary(primary_payload, signal.ticker)
            self._queue_enriched(enriched_payload, signal.ticker)
            logger.warning(
                "Redis unavailable; queued primary payload and optional enriched payload for ticker=%s",
                signal.ticker,
            )
            return False

    async def _try_reconnect(self) -> None:
        logger.info("Attempting Redis reconnect")
        try:
            if self._client is not None:
                await self._client.aclose()
            await self.connect()
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("Redis reconnect failed: %s", exc)
            await asyncio.sleep(self._reconnect_delay)

    async def _flush_backup_queues(self) -> None:
        if self._client is None:
            return

        if not self._primary_backup_queue and not self._enriched_backup_queue:
            return

        logger.info(
            "Flushing queued Redis payload(s): primary=%d enriched=%d",
            len(self._primary_backup_queue),
            len(self._enriched_backup_queue),
        )

        while self._primary_backup_queue:
            try:
                await self._client.publish(self._channel, self._primary_backup_queue.popleft())
            except Exception as exc:  # pragma: no cover - network dependent
                self._connected = False
                logger.error("Primary backup flush interrupted: %s", exc)
                return

        if not self._enriched_channel:
            return

        while self._enriched_backup_queue:
            try:
                await self._client.publish(
                    self._enriched_channel,
                    self._enriched_backup_queue.popleft(),
                )
            except Exception as exc:  # pragma: no cover - network dependent
                self._connected = False
                logger.error("Enriched backup flush interrupted: %s", exc)
                return

    def _queue_primary(self, payload: str, ticker: str) -> None:
        if len(self._primary_backup_queue) < self._backup_max:
            self._primary_backup_queue.append(payload)
            return
        logger.error("Primary backup queue is full; dropping ticker=%s", ticker)

    def _queue_enriched(self, payload: Optional[str], ticker: str) -> None:
        if not self._enriched_channel or payload is None:
            return
        if len(self._enriched_backup_queue) < self._backup_max:
            self._enriched_backup_queue.append(payload)
            return
        logger.warning(
            "Enriched backup queue is full; dropping enriched payload for ticker=%s",
            ticker,
        )

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def backup_queue_size(self) -> int:
        return len(self._primary_backup_queue) + len(self._enriched_backup_queue)
