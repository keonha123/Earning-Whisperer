"""Helpers for adapting internal signals to project-wide service contracts."""

from __future__ import annotations

from models.contract_models import BackendRedisSignal
from models.signal_models import TradingSignalV3


def to_backend_redis_signal(signal: TradingSignalV3, *, is_session_end: bool) -> BackendRedisSignal:
    """Convert the richer internal signal into the minimal backend contract."""

    return BackendRedisSignal(
        ticker=signal.ticker,
        raw_score=round(signal.raw_score, 4),
        rationale=signal.rationale,
        text_chunk=signal.text_chunk,
        timestamp=signal.timestamp,
        is_session_end=is_session_end,
    )

