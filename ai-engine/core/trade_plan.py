from __future__ import annotations

from typing import Any

try:
    from models.request_models import MarketData
    from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
except ImportError:  # pragma: no cover
    from ..models.request_models import MarketData
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


_CONTINUATION = {
    StrategyName.MOMENTUM_CARRY,
    StrategyName.PEAD,
    StrategyName.GAP_AND_GO,
    StrategyName.WHISPER_PLAY,
    StrategyName.SHORT_SQUEEZE,
    StrategyName.NEWS_BREAKOUT,
}

_MEAN_REVERSION = {
    StrategyName.GAP_FILL,
    StrategyName.REVERSAL_CATALYST,
}


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _direction_sign(analysis: GeminiAnalysisResult | None) -> int:
    if analysis is None:
        return 1
    if analysis.direction == "BEARISH":
        return -1
    return 1


def build_trade_plan(
    market_data: MarketData,
    decision: StrategyDecision,
    analysis: GeminiAnalysisResult | None = None,
) -> dict[str, Any]:
    price = market_data.current_price
    if not price or price <= 0:
        return {
            "available": False,
            "reason": "missing_price",
        }

    atr_pct = market_data.atr_pct_14 or 0.025
    atr_pct = max(0.008, min(atr_pct, 0.12))
    atr_value = price * atr_pct
    gap_abs_pct = abs(market_data.gap_pct or 0.0) / 100.0
    direction = _direction_sign(analysis)

    plan: dict[str, Any] = {
        "available": True,
        "strategy": decision.strategy.value,
        "direction": "LONG" if direction > 0 else "SHORT",
        "reference_price": _round_price(price),
        "atr_pct_14": round(atr_pct * 100.0, 3),
        "hold_days": decision.hold_days,
        "sizing_hint": "half_size" if any(flag in decision.risk_flags for flag in {"high_vix", "thin_confirmation", "overextended_rsi"}) else "full_size",
    }

    if decision.strategy in _CONTINUATION:
        pullback_buffer = 0.35 * atr_value
        breakout_buffer = 0.12 * atr_value
        stop_buffer = 0.95 * atr_value
        tp1_buffer = max(1.1 * atr_value, 0.5 * gap_abs_pct * price)
        tp2_buffer = max(2.0 * atr_value, 0.9 * gap_abs_pct * price)

        if direction > 0:
            entry_low = price - pullback_buffer
            entry_high = price + breakout_buffer
            stop = entry_low - stop_buffer
            tp1 = price + tp1_buffer
            tp2 = price + tp2_buffer
        else:
            entry_low = price - breakout_buffer
            entry_high = price + pullback_buffer
            stop = entry_high + stop_buffer
            tp1 = price - tp1_buffer
            tp2 = price - tp2_buffer

        plan.update(
            {
                "setup_type": "continuation",
                "entry_style": "buy_pullback_or_breakout" if direction > 0 else "sell_rip_or_breakdown",
                "entry_zone": [_round_price(min(entry_low, entry_high)), _round_price(max(entry_low, entry_high))],
                "stop_loss": _round_price(stop),
                "take_profit_1": _round_price(tp1),
                "take_profit_2": _round_price(tp2),
                "time_stop_days": min(decision.hold_days, 3 if decision.strategy == StrategyName.GAP_AND_GO else decision.hold_days),
                "execution_notes": [
                    "partial at first target, trail remainder on strength",
                    "avoid chasing if price extends beyond upper trigger by >0.8 ATR",
                ],
            }
        )
        return plan

    if decision.strategy in _MEAN_REVERSION:
        reversion_buffer = 0.22 * atr_value
        stop_buffer = 0.85 * atr_value
        tp1_buffer = max(0.9 * atr_value, 0.45 * gap_abs_pct * price)
        tp2_buffer = max(1.5 * atr_value, 0.8 * gap_abs_pct * price)

        if direction > 0:
            entry_low = price - reversion_buffer
            entry_high = price + 0.08 * atr_value
            stop = entry_low - stop_buffer
            tp1 = price + tp1_buffer
            tp2 = price + tp2_buffer
        else:
            entry_low = price - 0.08 * atr_value
            entry_high = price + reversion_buffer
            stop = entry_high + stop_buffer
            tp1 = price - tp1_buffer
            tp2 = price - tp2_buffer

        plan.update(
            {
                "setup_type": "mean_reversion",
                "entry_style": "fade_extension_after_rejection" if direction < 0 else "buy_flush_after_stabilization",
                "entry_zone": [_round_price(min(entry_low, entry_high)), _round_price(max(entry_low, entry_high))],
                "stop_loss": _round_price(stop),
                "take_profit_1": _round_price(tp1),
                "take_profit_2": _round_price(tp2),
                "time_stop_days": min(decision.hold_days, 2),
                "execution_notes": [
                    "require evidence of stall/rejection before entry",
                    "do not hold reversion trade if trend resumes with volume expansion",
                ],
            }
        )
        return plan

    if decision.strategy == StrategyName.IV_CRUSH_DECAY:
        premium_buffer = max(0.8 * atr_value, 0.35 * gap_abs_pct * price)
        plan.update(
            {
                "setup_type": "volatility_decay",
                "entry_style": "event_passed_wait_for_vol_compression",
                "entry_zone": [_round_price(price - 0.15 * atr_value), _round_price(price + 0.15 * atr_value)],
                "stop_loss": _round_price(price + direction * premium_buffer * -1),
                "take_profit_1": _round_price(price + direction * 0.75 * atr_value),
                "take_profit_2": _round_price(price + direction * 1.25 * atr_value),
                "time_stop_days": min(decision.hold_days, 2),
                "execution_notes": [
                    "best used after the catalyst once implied volatility begins to normalize",
                    "prefer defined-risk structures when spreads widen",
                ],
            }
        )
        return plan

    plan.update(
        {
            "setup_type": "sentiment_only",
            "entry_style": "no_trade_or_micro_size",
            "entry_zone": [_round_price(price), _round_price(price)],
            "stop_loss": _round_price(price - direction * atr_value),
            "take_profit_1": _round_price(price + direction * atr_value),
            "take_profit_2": _round_price(price + direction * 1.8 * atr_value),
            "time_stop_days": 1,
            "execution_notes": ["insufficient edge; use minimal risk or skip"],
        }
    )
    return plan
