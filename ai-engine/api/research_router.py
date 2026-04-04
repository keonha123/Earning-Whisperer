"""Research endpoints for backtesting and execution-style inspection."""

from __future__ import annotations

from fastapi import APIRouter

from ..core.backtester import (
    SignalRecord,
    recommend_gate_adjustment,
    recommend_operating_mode,
    run_backtest,
)
from ..core.execution_style import recommend_execution_style
from ..models.research_models import BacktestRequest, StyleRecommendationRequest

router = APIRouter(prefix="/api/v1/research", tags=["research"])


@router.post("/backtest")
async def backtest(request: BacktestRequest) -> dict:
    records = [
        SignalRecord(
            ticker=item.ticker,
            timestamp=item.timestamp,
            composite_score=item.composite_score,
            raw_score=item.raw_score,
            trade_approved=item.trade_approved,
            strategy=item.strategy,
            actual_return=item.actual_return,
        )
        for item in request.records
    ]
    result = run_backtest(records)
    action, reason = recommend_gate_adjustment(result)
    operating_mode = recommend_operating_mode(result)
    return {
        "backtest": result.to_dict(),
        "gate_recommendation": {"action": action, "reason": reason},
        "operating_mode": operating_mode,
    }


@router.post("/style")
async def style(request: StyleRecommendationRequest) -> dict:
    recommendation = recommend_execution_style(
        strategy=request.strategy,
        composite_score=request.composite_score,
        confidence=request.confidence,
        trade_approved=request.trade_approved,
        market_data=request.market_data,
        section_type=request.section_type,
    )
    return {
        "style": recommendation.style,
        "max_trades_per_session": recommendation.max_trades_per_session,
        "max_holding_minutes": recommendation.max_holding_minutes,
        "rationale": recommendation.rationale,
    }

