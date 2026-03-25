# ═══════════════════════════════════════════════════════════════════════════
# core/redis_publisher.py
# Redis trading-signals 채널 발행
# Contract 2: AI Engine → Backend
# ═══════════════════════════════════════════════════════════════════════════
import logging
import redis.asyncio as aioredis
from models.signal_models import TradingSignalV3
from config import settings

logger = logging.getLogger("redis_publisher")


class RedisPublisher:
    def __init__(self):
        self._client = None

    async def connect(self):
        self._client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        await self._client.ping()
        logger.info(f"Redis 연결 성공: {settings.redis_url}")

    async def publish(self, signal: TradingSignalV3) -> None:
        """
        TradingSignalV3 → JSON → Redis 채널 발행.
        null 필드 제외(exclude_none=True)로 페이로드 최소화.
        """
        if not self._client:
            await self.connect()

        # Pydantic v2: model_dump_json() — null 필드 제외
        payload = signal.model_dump_json(exclude_none=True)

        await self._client.publish(settings.redis_channel, payload)

        logger.info(
            f"[Redis 발행] ticker={signal.ticker} "
            f"raw_score={signal.raw_score:.3f} "
            f"composite={signal.composite_score} "
            f"approved={signal.trade_approved} "
            f"strategy={signal.primary_strategy}"
        )

    async def close(self):
        if self._client:
            await self._client.aclose()
            logger.info("Redis 연결 해제")


# 싱글턴
redis_publisher = RedisPublisher()
