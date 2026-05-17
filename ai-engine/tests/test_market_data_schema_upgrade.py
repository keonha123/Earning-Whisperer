from __future__ import annotations

from models.request_models import MarketData


def test_market_data_accepts_extended_execution_and_whisper_fields() -> None:
    payload = {
        'ticker': 'AAPL',
        'current_price': 201.5,
        'prev_close': 198.0,
        'volume_ratio': 1.9,
        'gap_pct': 1.8,
        'surprise_pct': 6.5,
        'implied_move_pct': 3.4,
        'bid_ask_spread_bps': 12.0,
        'premarket_volume_ratio': 1.6,
        'whisper_eps': 1.91,
        'avg_analyst_estimate': 1.84,
        'market_cap': 3000000000000,
        'bb_position': 0.72,
        'atr_14': 4.1,
        'low_52w': 164.0,
    }
    item = MarketData.model_validate(payload)

    assert item.ticker == 'AAPL'
    assert item.prev_close == 198.0
    assert item.implied_move_pct == 3.4
    assert item.bid_ask_spread_bps == 12.0
    assert item.whisper_eps == 1.91
    assert item.market_cap == 3000000000000
