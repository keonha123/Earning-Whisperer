from __future__ import annotations

import json
from collections import deque

import pytest

from ..core.redis_publisher import RedisPublisher
from ..models.contract_models import BackendRedisSignal
from ..models.signal_models import TradingSignalV3


def _make_signal(ticker: str) -> TradingSignalV3:
    return TradingSignalV3(
        ticker=ticker,
        raw_score=0.6,
        rationale=f"{ticker} rationale",
        text_chunk=f"{ticker} transcript chunk",
        timestamp=1743724800,
    )


def _make_backend_signal(ticker: str) -> BackendRedisSignal:
    return BackendRedisSignal(
        ticker=ticker,
        raw_score=0.6,
        rationale=f"{ticker} rationale",
        text_chunk=f"{ticker} transcript chunk",
        timestamp=1743724800,
        is_session_end=False,
    )


class _DummyRedisClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.messages.append((channel, payload))


@pytest.mark.asyncio
async def test_primary_backup_queue_is_not_displaced_by_enriched_messages(monkeypatch):
    publisher = RedisPublisher()
    publisher._connected = False
    publisher._backup_max = 1
    publisher._primary_backup_queue = deque(maxlen=1)
    publisher._enriched_backup_queue = deque(maxlen=1)

    async def _no_reconnect() -> None:
        return None

    monkeypatch.setattr(publisher, "_try_reconnect", _no_reconnect)

    await publisher.publish(_make_signal("NVDA"), backend_signal=_make_backend_signal("NVDA"))
    await publisher.publish(_make_signal("AMD"), backend_signal=_make_backend_signal("AMD"))

    assert publisher.backup_queue_size == 2

    primary_payload = json.loads(publisher._primary_backup_queue[0])
    enriched_payload = json.loads(publisher._enriched_backup_queue[0])

    assert primary_payload["ticker"] == "NVDA"
    assert enriched_payload["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_backup_flush_prioritizes_primary_channel_before_enriched_channel():
    publisher = RedisPublisher()
    publisher._client = _DummyRedisClient()
    publisher._connected = True
    publisher._primary_backup_queue.append('{"ticker":"QUEUED_PRIMARY"}')
    publisher._enriched_backup_queue.append('{"ticker":"QUEUED_ENRICHED"}')

    published = await publisher.publish(
        _make_signal("MSFT"),
        backend_signal=_make_backend_signal("MSFT"),
    )

    assert published is True
    assert publisher._client.messages[0][0] == publisher._channel
    assert publisher._client.messages[1][0] == publisher._enriched_channel
    assert publisher._client.messages[2][0] == publisher._channel
    assert publisher._client.messages[3][0] == publisher._enriched_channel

    first_payload = json.loads(publisher._client.messages[0][1])
    second_payload = json.loads(publisher._client.messages[1][1])
    assert first_payload["ticker"] == "QUEUED_PRIMARY"
    assert second_payload["ticker"] == "QUEUED_ENRICHED"
