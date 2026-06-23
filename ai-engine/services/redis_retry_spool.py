"""Durable JSONL spool for Redis publish retries."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Any
from uuid import uuid4


class RedisRetrySpool:
    def __init__(self, path: str | Path, *, max_entries: int = 5000) -> None:
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()

    def append(self, *, channel: str, payload: dict[str, Any], error: str) -> dict[str, Any]:
        entry = {
            "retry_id": str(uuid4()),
            "channel": channel,
            "payload": payload,
            "attempts": 0,
            "last_error": error,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        with self._lock:
            entries = self.load()
            entries.append(entry)
            self.replace(entries[-self.max_entries :])
        return entry

    def load(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            entries: list[dict[str, Any]] = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return entries[:limit] if limit is not None else entries

    def replace(self, entries: list[dict[str, Any]]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            body = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":"), default=str) + "\n" for item in entries)
            temporary.write_text(body, encoding="utf-8")
            temporary.replace(self.path)

    def count(self) -> int:
        return len(self.load())


__all__ = ["RedisRetrySpool"]
