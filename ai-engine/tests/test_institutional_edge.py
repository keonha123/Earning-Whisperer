from __future__ import annotations

from core.institutional_edge import build_institutional_edge
from models.request_models import MarketData, SourceType
from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


def test_institutional_edge_marks_well_supported_signal_actionable() -> None:
    market_data = MarketData(
        ticker="NVDA",
        current_price=100.0,
        avg_volume_20d=15_000_000,
        volume_ratio=2.4,
        liquidity_score=0.88,
        bid_ask_spread_bps=12.0,
        atr_pct_14=2.1,
        surprise_pct=6.2,
        gap_pct=3.4,
        relative_strength_20d=5.1,
    )
    analysis = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.74,
        confidence=0.87,
        rationale="guidance and demand commentary improved",
        catalyst_type="GUIDANCE_UP",
        disagreement_score=0.05,
        metadata={
            "feature_bundle": {"coverage_pct": 62.0},
            "source_health_summary": {"coverage_pct": 85.0},
        },
    )
    decision = StrategyDecision(
        strategy=StrategyName.PEAD,
        score=0.83,
        hold_days=3,
        rationale="post-earnings drift setup",
    )
    signal_explanation = {
        "feature_contributions": [{"feature": "guidance", "direction": "positive", "magnitude": 0.8}],
        "top_drivers": ["guidance improved", "volume confirmed", "relative strength expanded"],
        "top_risks": ["gap could fade"],
    }
    trade_plan = {
        "available": True,
        "entry_zone": [99.2, 101.0],
        "stop_loss": 96.5,
        "time_stop_days": 3,
    }

    edge = build_institutional_edge(
        market_data=market_data,
        analysis=analysis,
        strategy_decision=decision,
        source_type=SourceType.EARNINGS_CALL,
        signal_explanation=signal_explanation,
        trade_plan=trade_plan,
        product_surface={"actionability_score": 0.82},
    )

    assert edge["approval_state"] == "institutional_actionable"
    assert edge["institutional_grade_score"] >= 76
    assert edge["capacity"]["estimated_capacity_usd"] is not None
    assert "red_team_opposing_thesis" in edge["moat_vs_retail_ai"]
    assert edge["red_team"]["what_would_change_mind"]


def test_institutional_edge_downgrades_neutral_or_under_supported_signal() -> None:
    market_data = MarketData(ticker="TSLA", current_price=100.0, volume_ratio=0.6, liquidity_score=0.2)
    analysis = GeminiAnalysisResult(
        direction="NEUTRAL",
        magnitude=0.0,
        confidence=0.1,
        rationale="fallback",
        catalyst_type="UNCLASSIFIED",
        metadata={"llm_error": {"stage": "response_parse_or_schema_validation"}},
    )
    decision = StrategyDecision(
        strategy=StrategyName.SENTIMENT_ONLY,
        score=0.2,
        hold_days=1,
        rationale="no actionable setup",
        risk_flags=["weak_setup"],
    )

    edge = build_institutional_edge(
        market_data=market_data,
        analysis=analysis,
        strategy_decision=decision,
        source_type=SourceType.NEWS,
        signal_explanation={},
        trade_plan={"available": False},
    )

    assert edge["approval_state"] in {"research_only", "retail_summary_only"}
    assert "llm_fallback" in edge["blockers"]
    assert "no_directional_edge" in edge["blockers"]
