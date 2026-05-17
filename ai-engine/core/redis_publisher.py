from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RedisPublisher:
    """Compatibility-safe no-op publisher for local validation and tests."""

    published_messages: list[tuple[str, Any]] = field(default_factory=list)

    async def publish(self, channel: str, payload: Any) -> bool:
        self.published_messages.append((channel, payload))
        return True
