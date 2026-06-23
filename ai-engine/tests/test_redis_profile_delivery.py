from __future__ import annotations

import json

import pytest

from config import Settings
from models.legacy_contract_models import LegacySignalMessage
from services.redis_signal_publisher import RedisSignalPublisher


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages = []

    async def publish(self, channel, encoded):
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.messages.append((channel, encoded))
        return 1


@pytest.mark.asyncio
async def test_profile_channels_are_published_and_failed_messages_are_replayed(tmp_path) -> None:
    settings = Settings(
        redis_retry_spool_path=str(tmp_path / "redis-spool.jsonl"),
        redis_retry_auto_flush_limit=0,
        redis_profile_publish_enabled=True,
    )
    publisher = RedisSignalPublisher(settings)
    failing = FakeRedis(fail=True)
    publisher._client = failing
    signal = LegacySignalMessage(
        ticker="NVDA",
        raw_score=0.4,
        rationale="test",
        text_chunk="guidance raised",
        timestamp=1,
        investment_profile="NASDAQ100_AGGRESSIVE",
        strategy_recommendation={"redis_channel_hint": "trading-signals:nasdaq100:aggressive"},
    )

    failed = await publisher.publish(legacy_signal=signal, enriched_message={"ticker": "NVDA"})
    assert failed.retry_queued == 4
    assert publisher.retry_spool.count() == 4

    healthy = FakeRedis()
    publisher._client = healthy
    replay = await publisher.retry_pending(limit=10)
    assert replay.published == 4
    assert replay.remaining == 0
    channels = {item[0] for item in healthy.messages}
    assert "trading-signals:nasdaq100:aggressive" in channels
    assert "trading-signals:nasdaq100:aggressive:enriched" in channels
    legacy_payload = next(json.loads(encoded) for channel, encoded in healthy.messages if channel == settings.redis_channel)
    assert legacy_payload["raw_score"] == 0.4
    assert legacy_payload["ai_score"] == 0.4
