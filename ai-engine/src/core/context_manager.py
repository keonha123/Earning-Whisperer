"""Sliding-window transcript context management keyed by per-call session ids."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

logger = logging.getLogger(__name__)


@dataclass
class ChunkRecord:
    """A single transcript fragment kept in the rolling context window."""

    sequence: int
    text_chunk: str
    timestamp: int


@dataclass
class ContextSession:
    """Rolling transcript state for one earnings-call session key."""

    session_key: str
    chunks: Deque[ChunkRecord] = field(default_factory=deque)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    is_closed: bool = False


class ContextManager:
    """Maintain a bounded chunk history per session key.

    Session keys may be plain tickers or call-scoped ids such as
    ``NVDA:call-001``. The API uses ``session_key`` consistently so the
    interface matches real usage in the router layer.
    """

    def __init__(self, history_size: int = 5, session_ttl: int = 3600) -> None:
        self._history_size = history_size
        self._session_ttl = session_ttl
        self._sessions: dict[str, ContextSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def update(
        self,
        session_key: str,
        chunk: ChunkRecord,
        is_final: bool = False,
    ) -> None:
        """Append a chunk to a session and optionally close it."""

        lock = await self._get_or_create_lock(session_key)

        async with lock:
            session = self._sessions.get(session_key)
            if session is None or session.is_closed:
                session = ContextSession(session_key=session_key)
                self._sessions[session_key] = session
                logger.debug("Session created: session_key=%s", session_key)

            session.chunks.append(chunk)
            if len(session.chunks) > self._history_size:
                session.chunks.popleft()

            session.last_updated = time.time()

            if is_final:
                session.is_closed = True
                logger.info(
                    "Session closed: session_key=%s total_chunks=%d",
                    session_key,
                    len(session.chunks),
                )

    async def get_context(self, session_key: str) -> list[ChunkRecord]:
        """Return the recent context window for one session key."""

        lock = await self._get_or_create_lock(session_key)

        async with lock:
            session = self._sessions.get(session_key)
            if session is None:
                return []
            return list(session.chunks)

    async def get_active_tickers(self) -> list[str]:
        """Return active session keys that are not closed yet."""

        async with self._global_lock:
            return [
                session_key
                for session_key, session in self._sessions.items()
                if not session.is_closed
            ]

    async def cleanup_expired(self) -> int:
        """Remove expired sessions without deleting freshly updated state."""

        now = time.time()
        expired_candidates: list[str] = []

        async with self._global_lock:
            for session_key, session in self._sessions.items():
                if now - session.last_updated > self._session_ttl:
                    expired_candidates.append(session_key)

        cleaned = 0
        for session_key in expired_candidates:
            lock = await self._get_or_create_lock(session_key)
            async with lock:
                async with self._global_lock:
                    session = self._sessions.get(session_key)
                    if session is None:
                        continue

                    age = time.time() - session.last_updated
                    if age <= self._session_ttl:
                        continue

                    self._sessions.pop(session_key, None)
                    self._locks.pop(session_key, None)
                    cleaned += 1
                    logger.info("Expired session cleaned: session_key=%s", session_key)

        return cleaned

    async def _get_or_create_lock(self, session_key: str) -> asyncio.Lock:
        """Return the per-session lock, creating it when needed."""

        async with self._global_lock:
            if session_key not in self._locks:
                self._locks[session_key] = asyncio.Lock()
            return self._locks[session_key]
