from __future__ import annotations

from core.context_manager import ChunkRecord, RollingContextManager, novelty_against_context
from core.phase1_scorer import score_phase1
from models.request_models import MarketData, SectionType, SourceType


def _market_data() -> MarketData:
    return MarketData.model_validate(
        {
            'ticker': 'MSFT',
            'current_price': 420.0,
            'gap_pct': 2.1,
            'surprise_pct': 6.0,
            'post_earnings_drift_pct': 2.0,
            'short_interest_pct_float': 0.7,
            'float_rotation': 0.2,
            'iv_rank': 18.0,
            'current_iv': 0.31,
            'day1_return_pct': 1.7,
            'volume_ratio': 1.6,
            'relative_strength_20d': 4.8,
            'sector_momentum': 3.4,
            'vix': 17.0,
            'beta_20d': 1.1,
            'liquidity_score': 0.88,
            'next_earnings_days': 21,
            'rsi_14': 61.0,
        }
    )


def test_phase1_highlights_material_earnings_language() -> None:
    result = score_phase1(
        current_chunk='Revenue grew 28% year over year and operating margin expanded 220 basis points with raised guidance.',
        market_data=_market_data(),
        section_type=SectionType.PREPARED_REMARKS,
        source_type=SourceType.EARNINGS_CALL,
    )

    assert result.raw_score > 0
    assert result.provider in {'hybrid', 'hybrid:heuristic_fallback', 'heuristic'}
    assert result.label in {'pass', 'review', 'drop'}


def test_context_manager_keeps_recent_chunks_and_novelty_drops_for_duplicates() -> None:
    manager = RollingContextManager(max_chunks=3)
    ticker = 'MSFT'
    first = ChunkRecord(text_chunk='AI demand remained strong across Azure.', section_type=SectionType.PREPARED_REMARKS, source_type=SourceType.EARNINGS_CALL, raw_score=2.0)
    second = ChunkRecord(text_chunk='AI demand remained strong across Azure with improving backlog.', section_type=SectionType.PREPARED_REMARKS, source_type=SourceType.EARNINGS_CALL, raw_score=2.1)
    third = ChunkRecord(text_chunk='Commercial bookings accelerated sequentially.', section_type=SectionType.PREPARED_REMARKS, source_type=SourceType.EARNINGS_CALL, raw_score=1.5)
    fourth = ChunkRecord(text_chunk='Capital expenditures will remain elevated next quarter.', section_type=SectionType.PREPARED_REMARKS, source_type=SourceType.EARNINGS_CALL, raw_score=1.8)

    manager.add(ticker, first)
    manager.add(ticker, second)
    manager.add(ticker, third)
    manager.add(ticker, fourth)

    context = manager.get(ticker)
    assert len(context) == 3
    assert context[0].text == second.text

    novelty = novelty_against_context('AI demand remained strong across Azure.', context)
    assert 0.0 <= novelty < 1.0
