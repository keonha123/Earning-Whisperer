from __future__ import annotations

import json
from pathlib import Path


class NewsStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: set[str] = set()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._seen = set()
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._seen = set()
            return
        self._seen = {str(item) for item in payload if item}

    def is_seen(self, key: str) -> bool:
        return key in self._seen

    def mark_many(self, keys: list[str]) -> None:
        self._seen.update(keys)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(sorted(self._seen), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
