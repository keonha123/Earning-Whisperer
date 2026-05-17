from __future__ import annotations

from core.decision_assistant import build_decision_assistant
from models.request_models import MarketData, SourceType
from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


def _decision(
    *,
    strategy: StrategyName = StrategyName.PEAD,
    score: float = 0.82,
    risk_flags: list[str] | None = None,
) -> StrategyDecision:
    return StrategyDecision(
        strategy=strategy,
        score=score,
        hold_days=4,
        rationale="validated setup",
        risk_flags=risk_flags or [],
        metadata={},
    )


def test_decision_assistant_adds_verified_add_guidance_for_clean_bullish_signal() -> None:
    analysis = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.78,
        confidence=0.86,
        rationale="beat and raise",
        catalyst_type="GUIDANCE_UP",
        metadata={"universe_profile": "NASDAQ100", "risk_style": "conservative"},
    )
    market_data = MarketData(
        ticker="NVDA",
        current_price=950.0,
        bid_ask_spread_bps=10.0,
        surprise_pct=8.5,
        volume_ratio=2.4,
        relative_strength_20d=6.2,
        qqq_relative_strength_20d=1.5,
        sector_code="semiconductors",
        market_cap_bucket="mega",
    )

    payload = build_decision_assistant(
        market_data=market_data,
        analysis=analysis,
        strategy_decision=_decision(),
        source_type=SourceType.EARNINGS_CALL,
        signal_explanation={"key_factors_ko": ["가이던스 상향"]},
        trade_plan={"entry_style": "buy_pullback_or_breakout"},
        product_surface={"actionability_score": 0.84},
    )

    assert payload["sell_first"]["action"] == "ADD"
    assert payload["replay_confidence_badge"]["available"] is True
    assert payload["execution_badge"]["label"] == "실행 가능"
    assert payload["order_draft_preview"]["broker_execution"] == "not_called"
    assert payload["frontend_cards"]["hero"]["badge"] == "매수 가능"


def test_decision_assistant_blocks_entry_when_execution_cost_is_too_high() -> None:
    analysis = GeminiAnalysisResult(
        direction="BULLISH",
        magnitude=0.75,
        confidence=0.88,
        rationale="strong but expensive",
        catalyst_type="NEWS_BREAKOUT",
        metadata={"universe_profile": "NASDAQ100", "risk_style": "conservative"},
    )
    market_data = MarketData(
        ticker="TSLA",
        current_price=250.0,
        bid_ask_spread_bps=40.0,
        surprise_pct=4.0,
        volume_ratio=2.0,
    )

    payload = build_decision_assistant(
        market_data=market_data,
        analysis=analysis,
        strategy_decision=_decision(strategy=StrategyName.NEWS_BREAKOUT),
        source_type=SourceType.NEWS,
        signal_explanation={},
        trade_plan={},
        product_surface={"actionability_score": 0.80},
    )

    assert payload["execution_badge"]["label"] == "진입 금지"
    assert payload["no_trade_explainer"]["blocked"] is True
    assert payload["sell_first"]["action"] == "AVOID"


def test_decision_assistant_reduces_or_exits_on_bearish_hard_risk() -> None:
    analysis = GeminiAnalysisResult(
        direction="BEARISH",
        magnitude=0.82,
        confidence=0.81,
        rationale="contradiction and weak guide",
        catalyst_type="GUIDANCE_DOWN",
        metadata={},
    )
    market_data = MarketData(
        ticker="AEHR",
        current_price=20.0,
        bid_ask_spread_bps=8.0,
        ma200=25.0,
        revenue_growth_yoy=-12.0,
        earnings_growth_yoy=-20.0,
        ichimoku_weekly_cloud_bias="bearish",
    )

    payload = build_decision_assistant(
        market_data=market_data,
        analysis=analysis,
        strategy_decision=_decision(strategy=StrategyName.REVERSAL_CATALYST, risk_flags=["management_contradiction_risk"]),
        source_type=SourceType.EARNINGS_CALL,
        signal_explanation={},
        trade_plan={},
        product_surface={"actionability_score": 0.70},
    )

    assert payload["sell_first"]["action"] in {"REDUCE", "EXIT", "AVOID"}
    assert "management_contradiction_risk" in payload["sell_first"]["risk_flags"]
    assert "weak_fundamentals" in payload["sell_first"]["risk_flags"]
