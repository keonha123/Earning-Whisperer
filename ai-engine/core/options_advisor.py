from __future__ import annotations

from typing import Any

try:
    from config import get_settings
    from models.request_models import MarketData
    from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from ..models.request_models import MarketData
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName


def _direction(analysis: GeminiAnalysisResult | None) -> str:
    if analysis is None:
        return "BULLISH"
    return analysis.direction if analysis.direction in {"BULLISH", "BEARISH"} else "BULLISH"


def _zero_dte_overlay(market_data: MarketData, direction: str) -> dict[str, Any] | None:
    if not market_data.zero_dte_available:
        return None

    gamma = float(market_data.zero_dte_gamma_pressure or 0.0)
    put_call_ratio = float(market_data.zero_dte_put_call_volume_ratio or 1.0)
    straddle_pct = market_data.zero_dte_atm_straddle_pct

    aligned = (
        (direction == "BULLISH" and gamma >= 0.10 and put_call_ratio <= 1.0)
        or (direction == "BEARISH" and gamma <= -0.10 and put_call_ratio >= 1.0)
    )
    if aligned:
        preferred_structure = "0dte_call_vertical_small" if direction == "BULLISH" else "0dte_put_vertical_small"
        stance = "selective_enabled"
        reason = "same-day options flow is directionally aligned, but size should stay small and defined-risk only"
    else:
        preferred_structure = None
        stance = "avoid"
        reason = "same-day options flow is mixed or opposing, so 0DTE execution should be avoided"

    return {
        "enabled": aligned,
        "stance": stance,
        "preferred_structure": preferred_structure,
        "reason": reason,
        "put_call_volume_ratio": round(put_call_ratio, 4) if market_data.zero_dte_put_call_volume_ratio is not None else None,
        "gamma_pressure": round(gamma, 4) if market_data.zero_dte_gamma_pressure is not None else None,
        "atm_straddle_pct": round(float(straddle_pct), 4) if straddle_pct is not None else None,
    }


def build_options_advice(
    market_data: MarketData,
    decision: StrategyDecision,
    analysis: GeminiAnalysisResult | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.options_advisor_enabled:
        return None

    direction = _direction(analysis)
    current_iv = market_data.current_iv
    rv_10d = market_data.realized_vol_10d
    iv_rv_ratio = None
    if current_iv is not None and rv_10d is not None and rv_10d > 0:
        iv_rv_ratio = round(current_iv / rv_10d, 3)

    data_quality_warning = None
    if current_iv is None:
        data_quality_warning = "missing_current_iv"

    if decision.strategy == StrategyName.IV_CRUSH_DECAY:
        structure = "bear_call_spread" if direction == "BEARISH" else "bull_put_spread"
        return {
            "enabled": True,
            "theme": "event_volatility_decay",
            "preferred_structure": structure,
            "reason": "prefer premium-selling only when volatility is elevated and risk is defined",
            "iv_rv_ratio": iv_rv_ratio,
            "data_quality_warning": data_quality_warning,
            "zero_dte_overlay": _zero_dte_overlay(market_data, direction),
        }

    continuation_strategies = {
        StrategyName.PEAD,
        StrategyName.GAP_AND_GO,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.WHISPER_PLAY,
        StrategyName.SHORT_SQUEEZE,
    }
    if decision.strategy in continuation_strategies:
        if iv_rv_ratio is not None and iv_rv_ratio <= 1.15:
            structure = "call_debit_spread" if direction == "BULLISH" else "put_debit_spread"
            reason = "directional continuation is cleaner when implied volatility is not excessively rich"
        elif iv_rv_ratio is not None and iv_rv_ratio >= 1.45:
            structure = "call_diagonal" if direction == "BULLISH" else "put_diagonal"
            reason = "rich front-end volatility argues for reducing premium paid while keeping directional exposure"
        else:
            structure = "defined_risk_vertical"
            reason = "use defined-risk directional spreads when volatility edge is unclear"
        return {
            "enabled": True,
            "theme": "directional_continuation",
            "preferred_structure": structure,
            "reason": reason,
            "iv_rv_ratio": iv_rv_ratio,
            "data_quality_warning": data_quality_warning,
            "zero_dte_overlay": _zero_dte_overlay(market_data, direction),
        }

    if decision.strategy in {StrategyName.GAP_FILL, StrategyName.REVERSAL_CATALYST}:
        structure = "short_term_vertical"
        return {
            "enabled": True,
            "theme": "mean_reversion",
            "preferred_structure": structure,
            "reason": "reversion setups decay quickly, so shorter-duration defined-risk structures are preferable",
            "iv_rv_ratio": iv_rv_ratio,
            "data_quality_warning": data_quality_warning,
            "zero_dte_overlay": _zero_dte_overlay(market_data, direction),
        }

    return {
        "enabled": False,
        "theme": "no_options_edge",
        "preferred_structure": None,
        "reason": "no clear volatility or directional structure edge",
        "iv_rv_ratio": iv_rv_ratio,
        "data_quality_warning": data_quality_warning,
        "zero_dte_overlay": _zero_dte_overlay(market_data, direction),
    }
