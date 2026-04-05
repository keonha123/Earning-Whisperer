from __future__ import annotations

import pytest

from core.integration_state import IntegrationStateStore
from models.integration_models import (
    CompanyUniverseItem,
    EarningsScheduleItem,
    MarketContextSnapshot,
)
from models.request_models import MarketData
from models.signal_models import (
    CatalystType,
    MarketRegime,
    SignalStrength,
    StrategyName,
    TradingSignalV3,
)


@pytest.mark.asyncio
async def test_merge_market_data_combines_cached_snapshot_and_request_payload():
    state = IntegrationStateStore()
    await state.upsert_market_data(
        ticker="NVDA",
        timestamp=1742000000,
        market_data=MarketData(
            current_price=900.0,
            volume_ratio=2.6,
            liquidity_score=0.88,
        ),
    )
    await state.set_market_context(
        MarketContextSnapshot(
            timestamp=1742000100,
            vix=18.4,
            put_call_ratio=0.91,
        )
    )

    merged = await state.merge_market_data(
        "NVDA",
        MarketData(
            current_price=905.0,
            gap_pct=3.2,
        ),
    )

    assert merged is not None
    assert merged.current_price == 905.0
    assert merged.volume_ratio == 2.6
    assert merged.vix == 18.4
    assert merged.put_call_ratio == 0.91
    assert merged.gap_pct == 3.2


@pytest.mark.asyncio
async def test_live_room_view_hides_trade_fields_and_keeps_context():
    state = IntegrationStateStore()
    await state.upsert_company_profiles(
        [CompanyUniverseItem(ticker="NVDA", company_name="NVIDIA", sector="Semiconductors")]
    )
    await state.upsert_schedules(
        [
            EarningsScheduleItem(
                ticker="NVDA",
                scheduled_at=1742000000,
                call_id="NVDA-2026Q1",
                company_name="NVIDIA",
            )
        ]
    )

    signal = TradingSignalV3(
        ticker="NVDA",
        raw_score=0.83,
        rationale="Raised guidance and strong data-center demand",
        text_chunk="We delivered record data-center revenue and raised our outlook.",
        timestamp=1742000300,
        composite_score=0.79,
        primary_strategy=StrategyName.GAP_AND_GO,
        signal_strength=SignalStrength.STRONG,
        market_regime=MarketRegime.BULL_TREND,
        catalyst_type=CatalystType.EARNINGS_BEAT,
        trade_approved=True,
        position_pct=0.18,
        stop_loss_price=880.0,
        take_profit_price=940.0,
    )
    await state.record_signal(
        session_key="NVDA:NVDA-2026Q1",
        signal=signal,
        call_id="NVDA-2026Q1",
        event_id="evt-1",
        source_type="STT_STREAM",
        section_type="Q_AND_A",
        speaker_role="CEO",
        speaker_name="Jensen",
    )

    view = await state.get_live_room_view("NVDA", call_id="NVDA-2026Q1")

    assert view is not None
    assert view.company_name == "NVIDIA"
    assert view.direction == "BULLISH"
    assert view.contains_trade_fields is False
    assert view.analysis_only is True
    assert "record data-center revenue" in view.text_excerpt


@pytest.mark.asyncio
async def test_capabilities_reflect_non_broker_architecture():
    state = IntegrationStateStore()
    await state.upsert_company_profiles([CompanyUniverseItem(ticker="AAPL", company_name="Apple")])

    capabilities = await state.capabilities()

    assert capabilities["broker_key_storage"] is False
    assert capabilities["broker_execution_mode"] == "desktop_local_callback"
    assert "AAPL" in capabilities["known_tickers"]

