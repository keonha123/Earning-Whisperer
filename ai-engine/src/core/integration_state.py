"""In-memory compatibility layer for collectors, live-room views, and desktop feedback."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..models.integration_models import (
    CompanyUniverseItem,
    DesktopExecutionFeedbackRequest,
    EarningsScheduleItem,
    LiveRoomSignalView,
    MarketContextSnapshot,
)
from ..models.request_models import MarketData
from ..models.signal_models import TradingSignalV3

logger = logging.getLogger(__name__)


@dataclass
class LatestSignalEnvelope:
    session_key: str
    signal: TradingSignalV3
    call_id: Optional[str]
    event_id: Optional[str]
    source_type: Optional[str]
    section_type: Optional[str]
    speaker_role: Optional[str]
    speaker_name: Optional[str]
    updated_at: int


class IntegrationStateStore:
    """Keeps lightweight state so independent teams can integrate incrementally."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._schedules_by_ticker: Dict[str, EarningsScheduleItem] = {}
        self._profiles_by_ticker: Dict[str, CompanyUniverseItem] = {}
        self._market_data_by_ticker: Dict[str, MarketData] = {}
        self._market_data_timestamp: Dict[str, int] = {}
        self._market_context: Optional[MarketContextSnapshot] = None
        self._latest_signals_by_session: Dict[str, LatestSignalEnvelope] = {}
        self._latest_session_by_ticker: Dict[str, str] = {}
        self._execution_feedback: List[DesktopExecutionFeedbackRequest] = []

    async def upsert_schedules(self, items: List[EarningsScheduleItem]) -> None:
        async with self._lock:
            for item in items:
                self._schedules_by_ticker[item.ticker] = item

    async def upsert_company_profiles(self, items: List[CompanyUniverseItem]) -> None:
        async with self._lock:
            for item in items:
                self._profiles_by_ticker[item.ticker] = item

    async def upsert_market_data(self, ticker: str, timestamp: int, market_data: MarketData) -> None:
        async with self._lock:
            self._market_data_by_ticker[ticker] = market_data
            self._market_data_timestamp[ticker] = timestamp

    async def set_market_context(self, snapshot: MarketContextSnapshot) -> None:
        async with self._lock:
            self._market_context = snapshot

    async def merge_market_data(
        self,
        ticker: str,
        request_market_data: Optional[MarketData],
    ) -> Optional[MarketData]:
        async with self._lock:
            merged = {}

            base = self._market_data_by_ticker.get(ticker)
            if base is not None:
                merged.update(base.model_dump(exclude_none=True))

            if self._market_context is not None:
                if self._market_context.vix is not None:
                    merged.setdefault("vix", self._market_context.vix)
                if self._market_context.put_call_ratio is not None:
                    merged.setdefault("put_call_ratio", self._market_context.put_call_ratio)

            if request_market_data is not None:
                merged.update(request_market_data.model_dump(exclude_none=True))

        if not merged:
            return request_market_data
        return MarketData(**merged)

    async def record_signal(
        self,
        *,
        session_key: str,
        signal: TradingSignalV3,
        call_id: Optional[str],
        event_id: Optional[str],
        source_type: Optional[str],
        section_type: Optional[str],
        speaker_role: Optional[str],
        speaker_name: Optional[str],
    ) -> None:
        envelope = LatestSignalEnvelope(
            session_key=session_key,
            signal=signal,
            call_id=call_id,
            event_id=event_id,
            source_type=source_type,
            section_type=section_type,
            speaker_role=speaker_role,
            speaker_name=speaker_name,
            updated_at=int(time.time()),
        )
        async with self._lock:
            self._latest_signals_by_session[session_key] = envelope
            self._latest_session_by_ticker[signal.ticker] = session_key

    async def get_live_room_view(
        self,
        ticker: str,
        *,
        call_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> Optional[LiveRoomSignalView]:
        async with self._lock:
            session_key = self._resolve_session_key(ticker, call_id=call_id, event_id=event_id)
            if session_key is None:
                return None

            envelope = self._latest_signals_by_session.get(session_key)
            if envelope is None:
                return None

            profile = self._profiles_by_ticker.get(ticker)
            schedule = self._schedules_by_ticker.get(ticker)
            signal = envelope.signal

        return LiveRoomSignalView(
            ticker=signal.ticker,
            company_name=(
                profile.company_name
                if profile and profile.company_name
                else schedule.company_name if schedule else None
            ),
            timestamp=signal.timestamp,
            updated_at=envelope.updated_at,
            call_id=envelope.call_id,
            event_id=envelope.event_id,
            source_type=envelope.source_type,
            section_type=envelope.section_type,
            speaker_role=envelope.speaker_role,
            speaker_name=envelope.speaker_name,
            direction=_direction_from_score(signal.raw_score),
            raw_score=signal.raw_score,
            composite_score=signal.composite_score,
            signal_strength=signal.signal_strength.value if signal.signal_strength else None,
            catalyst_type=signal.catalyst_type.value if signal.catalyst_type else None,
            market_regime=signal.market_regime.value if signal.market_regime else None,
            rationale=signal.rationale,
            text_excerpt=signal.text_chunk[:240],
            analysis_only=True,
            contains_trade_fields=False,
        )

    async def record_execution_feedback(
        self,
        request: DesktopExecutionFeedbackRequest,
    ) -> None:
        async with self._lock:
            self._execution_feedback.append(request)
            self._execution_feedback = self._execution_feedback[-200:]

    async def get_ticker_snapshot(self, ticker: str) -> dict:
        async with self._lock:
            profile = self._profiles_by_ticker.get(ticker)
            schedule = self._schedules_by_ticker.get(ticker)
            market_data = self._market_data_by_ticker.get(ticker)
            market_ts = self._market_data_timestamp.get(ticker)
            latest_session = self._latest_session_by_ticker.get(ticker)
            latest_signal = (
                self._latest_signals_by_session.get(latest_session) if latest_session else None
            )

        return {
            "ticker": ticker,
            "profile": profile.model_dump(exclude_none=True) if profile else None,
            "schedule": schedule.model_dump(exclude_none=True) if schedule else None,
            "market_data": market_data.model_dump(exclude_none=True) if market_data else None,
            "market_data_timestamp": market_ts,
            "latest_signal_timestamp": latest_signal.signal.timestamp if latest_signal else None,
            "latest_session_key": latest_session,
        }

    async def capabilities(self) -> dict:
        async with self._lock:
            known_tickers = sorted(
                set(self._profiles_by_ticker.keys())
                | set(self._market_data_by_ticker.keys())
                | set(self._schedules_by_ticker.keys())
            )
            return {
                "broker_key_storage": False,
                "broker_execution_mode": "desktop_local_callback",
                "collector_state_cache": True,
                "live_room_analysis_only_view": True,
                "batch_transcript_ingest": True,
                "market_context_supported": True,
                "known_tickers": known_tickers,
                "has_market_context": self._market_context is not None,
                "execution_feedback_buffer": len(self._execution_feedback),
            }

    def _resolve_session_key(
        self,
        ticker: str,
        *,
        call_id: Optional[str],
        event_id: Optional[str],
    ) -> Optional[str]:
        if call_id:
            return f"{ticker}:{call_id}"
        if event_id:
            return f"{ticker}:{event_id}"
        return self._latest_session_by_ticker.get(ticker)


def _direction_from_score(raw_score: float) -> str:
    if raw_score > 0.05:
        return "BULLISH"
    if raw_score < -0.05:
        return "BEARISH"
    return "NEUTRAL"
