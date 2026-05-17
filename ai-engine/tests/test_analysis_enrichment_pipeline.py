from __future__ import annotations

from core.analysis_enrichment import AnalysisEnrichmentPipeline
from models.request_models import MarketData, SectionType, SourceType
from models.signal_models import GeminiAnalysisResult


def test_enrichment_pipeline_adds_strategy_product_and_institutional_payloads() -> None:
    pipeline = AnalysisEnrichmentPipeline()
    analysis = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.72,
        confidence=0.84,
        rationale="guidance and demand improved",
        catalyst_type="GUIDANCE_UP",
        metadata={
            "feature_bundle": {"coverage_pct": 55.0},
            "source_health_summary": {"coverage_pct": 75.0},
        },
    )
    market_data = MarketData(
        ticker="NVDA",
        current_price=100.0,
        avg_volume_20d=12_000_000,
        volume_ratio=2.1,
        liquidity_score=0.82,
        bid_ask_spread_bps=14.0,
        surprise_pct=5.0,
        gap_pct=2.4,
        relative_strength_20d=4.5,
        atr_pct_14=2.2,
    )

    enriched = pipeline.enrich(
        market_data=market_data,
        analysis=analysis,
        section_type=SectionType.GUIDANCE,
        source_type=SourceType.EARNINGS_CALL,
        universe_profile="NASDAQ100",
    )

    assert enriched.strategy is not None
    assert enriched.metadata["trade_plan"]["available"] is True
    assert "signal_explanation" in enriched.metadata
    assert "product_surface" in enriched.metadata
    assert "institutional_edge" in enriched.metadata
    assert "decision_assistant" in enriched.metadata
    assert enriched.metadata["product_surface"]["institutional_edge"]["schema_version"] == "2026-04-26.institutional-edge.v1"
    assert enriched.metadata["product_surface"]["front_payload_ko"]["institutional_edge"]
    assert enriched.metadata["product_surface"]["decision_assistant"]["schema_version"] == "2026-05-03.decision-assistant.v1"
    assert enriched.metadata["product_surface"]["front_payload_ko"]["decision_assistant"]
