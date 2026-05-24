from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from time import time
from typing import Deque

try:
    from models.request_models import SectionType, SourceType
except ImportError:  # pragma: no cover
    from ..models.request_models import SectionType, SourceType


@dataclass(slots=True)
class ChunkRecord:
    sequence: int = 0
    text_chunk: str = ""
    timestamp: int | float = 0.0
    section_type: SectionType = SectionType.PREPARED_REMARKS
    source_type: SourceType = SourceType.EARNINGS_CALL
    raw_score: float = 0.0

    @property
    def text(self) -> str:
        return self.text_chunk


class RollingContextManager:
    def __init__(self, max_chunks: int = 5) -> None:
        self.max_chunks = max_chunks
        self._store: dict[str, Deque[ChunkRecord]] = defaultdict(lambda: deque(maxlen=max_chunks))

    def get(self, ticker: str) -> list[ChunkRecord]:
        return list(self._store[(ticker or '').upper()])

    def add(self, ticker: str, record: ChunkRecord) -> None:
        if record.timestamp == 0.0:
            record.timestamp = time()
        if record.sequence == 0:
            record.sequence = len(self._store[(ticker or '').upper()]) + 1
        self._store[(ticker or '').upper()].append(record)


def novelty_against_context(current_chunk: str, context_chunks: list[ChunkRecord]) -> float:
    if not context_chunks:
        return 1.0
    current = set(current_chunk.lower().split())
    if not current:
        return 0.0
    max_overlap = 0.0
    for chunk in context_chunks:
        other = set(chunk.text_chunk.lower().split())
        if not other:
            continue
        overlap = len(current & other) / max(1, len(current | other))
        max_overlap = max(max_overlap, overlap)
    return max(0.0, min(1.0, 1.0 - max_overlap))
