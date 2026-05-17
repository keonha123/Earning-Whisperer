"""Universe-specific strategy profiles for conservative and aggressive research tracks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Iterable

try:
    from core.alpha_formula_engine import AlphaFormula
    from models.signal_models import StrategyName
except ImportError:  # pragma: no cover
    from .alpha_formula_engine import AlphaFormula
    from ..models.signal_models import StrategyName


class UniverseName(str, Enum):
    DEFAULT = "DEFAULT"
    NASDAQ100 = "NASDAQ100"
    SP500 = "SP500"


class RiskStyleName(str, Enum):
    BALANCED = "BALANCED"
    CONSERVATIVE = "CONSERVATIVE"
    AGGRESSIVE = "AGGRESSIVE"


@dataclass(frozen=True)
class GateTuning:
    """Universe-specific tuning for the legacy five-gate compatibility layer."""

    composite_threshold_delta: float = 0.0
    confidence_threshold_delta: float = 0.0
    raw_score_threshold_delta: float = 0.0
    catalyst_volume_multiplier: float = 1.0
    long_rsi_overbought: float = 75.0
    short_rsi_oversold: float = 25.0
    max_vix: float | None = None
    blocked_regimes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyTuning:
    """Universe-specific thresholds and allowed strategies for strategy selection."""

    strategy_priority: tuple[StrategyName, ...]
    gap_min_pct: float
    gap_raw_min: float
    gap_premarket_min: float
    gap_relative_strength_min: float
    gap_liquidity_min: float
    gap_price_change_min: float
    gap_realized_vol_max: float | None
    gap_rsi_max: float | None
    gap_gap_cap_pct: float | None
    gap_above_ma20_required: bool
    gap_quality_min: float
    gap_volume_zscore_min: float | None
    gap_earnings_surprise_min: float | None
    gap_revision_min: float | None
    gap_first5_green_required: bool
    news_volume_min: float
    news_raw_min: float
    news_price_change_min: float
    news_relative_strength_min: float
    news_liquidity_min: float
    news_realized_vol_max: float | None
    news_gap_cap_pct: float | None
    news_rsi_max: float | None
    news_quality_min: float
    news_volume_zscore_min: float | None
    news_earnings_surprise_min: float | None
    news_revision_min: float | None
    news_hours_max: float | None
    news_distance_from_52w_high_min: float | None
    news_ma50_required: bool
    allowed_gap_catalysts: tuple[str, ...]
    preferred_news_catalysts: tuple[str, ...]
    enabled_strategies: tuple[StrategyName, ...] | None = None
    allow_sector_contagion: bool = False
    allow_sentiment_only: bool = False


@dataclass(frozen=True)
class RiskStyleProfile:
    """Risk-style overlay applied on top of a universe profile."""

    name: RiskStyleName
    description: str
    position_size_multiplier: float = 1.0


@dataclass(frozen=True)
class UniverseStrategyProfile:
    """Combined scoring, gate, and strategy behavior for a market universe."""

    name: UniverseName
    description: str
    formula_multiplier_sentiment: float
    formula_multiplier_sue: float
    formula_multiplier_momentum: float
    formula_multiplier_volume: float
    gate: GateTuning
    strategy: StrategyTuning
    risk_style_name: RiskStyleName = RiskStyleName.BALANCED

    def adjust_formula(self, formula: AlphaFormula) -> AlphaFormula:
        return AlphaFormula(
            w_sentiment=formula.w_sentiment * self.formula_multiplier_sentiment,
            w_sue=formula.w_sue * self.formula_multiplier_sue,
            w_momentum=formula.w_momentum * self.formula_multiplier_momentum,
            w_volume=formula.w_volume * self.formula_multiplier_volume,
        ).normalized()


SUPPORTED_ORCHESTRATOR_STRATEGIES: tuple[StrategyName, ...] = (
    StrategyName.PEAD,
    StrategyName.NEWS_BREAKOUT,
    StrategyName.MOMENTUM_CARRY,
    StrategyName.GAP_AND_GO,
    StrategyName.GAP_FILL,
    StrategyName.REVERSAL_CATALYST,
    StrategyName.SHORT_SQUEEZE,
    StrategyName.IV_CRUSH_DECAY,
    StrategyName.WHISPER_PLAY,
    StrategyName.SENTIMENT_ONLY,
)


def _priority(*strategies: StrategyName) -> tuple[StrategyName, ...]:
    return tuple(strategies)


def _base_strategy_tuning(
    *,
    strategy_priority: tuple[StrategyName, ...],
    enabled_strategies: tuple[StrategyName, ...] | None,
    allow_sentiment_only: bool,
    gap_min_pct: float = 3.0,
    gap_raw_min: float = 0.50,
    gap_premarket_min: float = 2.0,
    gap_relative_strength_min: float = 0.0,
    gap_liquidity_min: float = 0.25,
    gap_price_change_min: float = 0.25,
    gap_realized_vol_max: float | None = None,
    gap_rsi_max: float | None = None,
    gap_gap_cap_pct: float | None = None,
    gap_above_ma20_required: bool = False,
    gap_quality_min: float = 0.0,
    gap_volume_zscore_min: float | None = None,
    gap_earnings_surprise_min: float | None = None,
    gap_revision_min: float | None = None,
    gap_first5_green_required: bool = False,
    news_volume_min: float = 1.6,
    news_raw_min: float = 0.50,
    news_price_change_min: float = 0.75,
    news_relative_strength_min: float = 0.0,
    news_liquidity_min: float = 0.30,
    news_realized_vol_max: float | None = None,
    news_gap_cap_pct: float | None = None,
    news_rsi_max: float | None = None,
    news_quality_min: float = 0.0,
    news_volume_zscore_min: float | None = None,
    news_earnings_surprise_min: float | None = None,
    news_revision_min: float | None = None,
    news_hours_max: float | None = None,
    news_distance_from_52w_high_min: float | None = None,
    news_ma50_required: bool = False,
) -> StrategyTuning:
    return StrategyTuning(
        strategy_priority=strategy_priority,
        gap_min_pct=gap_min_pct,
        gap_raw_min=gap_raw_min,
        gap_premarket_min=gap_premarket_min,
        gap_relative_strength_min=gap_relative_strength_min,
        gap_liquidity_min=gap_liquidity_min,
        gap_price_change_min=gap_price_change_min,
        gap_realized_vol_max=gap_realized_vol_max,
        gap_rsi_max=gap_rsi_max,
        gap_gap_cap_pct=gap_gap_cap_pct,
        gap_above_ma20_required=gap_above_ma20_required,
        gap_quality_min=gap_quality_min,
        gap_volume_zscore_min=gap_volume_zscore_min,
        gap_earnings_surprise_min=gap_earnings_surprise_min,
        gap_revision_min=gap_revision_min,
        gap_first5_green_required=gap_first5_green_required,
        news_volume_min=news_volume_min,
        news_raw_min=news_raw_min,
        news_price_change_min=news_price_change_min,
        news_relative_strength_min=news_relative_strength_min,
        news_liquidity_min=news_liquidity_min,
        news_realized_vol_max=news_realized_vol_max,
        news_gap_cap_pct=news_gap_cap_pct,
        news_rsi_max=news_rsi_max,
        news_quality_min=news_quality_min,
        news_volume_zscore_min=news_volume_zscore_min,
        news_earnings_surprise_min=news_earnings_surprise_min,
        news_revision_min=news_revision_min,
        news_hours_max=news_hours_max,
        news_distance_from_52w_high_min=news_distance_from_52w_high_min,
        news_ma50_required=news_ma50_required,
        allowed_gap_catalysts=("EARNINGS_BEAT", "GUIDANCE_UP", "PRODUCT_NEWS"),
        preferred_news_catalysts=("EARNINGS_BEAT", "GUIDANCE_UP", "PRODUCT_NEWS"),
        enabled_strategies=enabled_strategies,
        allow_sector_contagion=False,
        allow_sentiment_only=allow_sentiment_only,
    )


DEFAULT_PROFILE = UniverseStrategyProfile(
    name=UniverseName.DEFAULT,
    description="Fallback profile when current index membership is unknown.",
    formula_multiplier_sentiment=1.0,
    formula_multiplier_sue=1.0,
    formula_multiplier_momentum=1.0,
    formula_multiplier_volume=1.0,
    gate=GateTuning(),
    strategy=_base_strategy_tuning(
        strategy_priority=_priority(
            StrategyName.PEAD,
            StrategyName.GAP_AND_GO,
            StrategyName.NEWS_BREAKOUT,
            StrategyName.MOMENTUM_CARRY,
            StrategyName.GAP_FILL,
            StrategyName.REVERSAL_CATALYST,
            StrategyName.SHORT_SQUEEZE,
            StrategyName.IV_CRUSH_DECAY,
            StrategyName.WHISPER_PLAY,
            StrategyName.SENTIMENT_ONLY,
        ),
        enabled_strategies=SUPPORTED_ORCHESTRATOR_STRATEGIES,
        allow_sentiment_only=True,
    ),
)


NASDAQ100_PROFILE = UniverseStrategyProfile(
    name=UniverseName.NASDAQ100,
    description="Growth-heavy universe with stronger preference for earnings and news continuation.",
    formula_multiplier_sentiment=1.0,
    formula_multiplier_sue=1.0,
    formula_multiplier_momentum=1.05,
    formula_multiplier_volume=0.95,
    gate=GateTuning(
        long_rsi_overbought=80.0,
        short_rsi_oversold=25.0,
        max_vix=30.0,
    ),
    strategy=_base_strategy_tuning(
        strategy_priority=_priority(
            StrategyName.PEAD,
            StrategyName.NEWS_BREAKOUT,
            StrategyName.MOMENTUM_CARRY,
            StrategyName.GAP_AND_GO,
            StrategyName.SHORT_SQUEEZE,
            StrategyName.REVERSAL_CATALYST,
            StrategyName.GAP_FILL,
            StrategyName.IV_CRUSH_DECAY,
            StrategyName.WHISPER_PLAY,
            StrategyName.SENTIMENT_ONLY,
        ),
        enabled_strategies=SUPPORTED_ORCHESTRATOR_STRATEGIES,
        allow_sentiment_only=False,
        gap_price_change_min=0.35,
        gap_realized_vol_max=0.060,
        gap_rsi_max=78.0,
        gap_gap_cap_pct=12.0,
        gap_above_ma20_required=True,
        news_volume_min=1.8,
        news_raw_min=0.62,
        news_price_change_min=1.25,
        news_relative_strength_min=0.04,
        news_liquidity_min=0.35,
        news_realized_vol_max=0.05,
        news_gap_cap_pct=10.0,
        news_rsi_max=76.0,
    ),
)


SP500_PROFILE = UniverseStrategyProfile(
    name=UniverseName.SP500,
    description="Broad-market universe with stricter continuation and lower-volatility bias.",
    formula_multiplier_sentiment=0.95,
    formula_multiplier_sue=1.05,
    formula_multiplier_momentum=1.10,
    formula_multiplier_volume=0.90,
    gate=GateTuning(
        composite_threshold_delta=-0.02,
        confidence_threshold_delta=-0.02,
        raw_score_threshold_delta=-0.01,
        catalyst_volume_multiplier=0.95,
        long_rsi_overbought=72.0,
        short_rsi_oversold=28.0,
        max_vix=27.0,
    ),
    strategy=_base_strategy_tuning(
        strategy_priority=_priority(
            StrategyName.GAP_AND_GO,
            StrategyName.PEAD,
            StrategyName.NEWS_BREAKOUT,
            StrategyName.GAP_FILL,
            StrategyName.REVERSAL_CATALYST,
            StrategyName.MOMENTUM_CARRY,
            StrategyName.SHORT_SQUEEZE,
            StrategyName.IV_CRUSH_DECAY,
            StrategyName.WHISPER_PLAY,
            StrategyName.SENTIMENT_ONLY,
        ),
        enabled_strategies=SUPPORTED_ORCHESTRATOR_STRATEGIES,
        allow_sentiment_only=False,
        gap_min_pct=2.5,
        gap_raw_min=0.42,
        gap_premarket_min=1.5,
        gap_relative_strength_min=0.01,
        gap_liquidity_min=0.30,
        gap_price_change_min=0.25,
        gap_realized_vol_max=0.055,
        gap_rsi_max=70.0,
        gap_gap_cap_pct=7.5,
        gap_above_ma20_required=True,
        news_volume_min=2.2,
        news_raw_min=0.68,
        news_price_change_min=0.8,
        news_relative_strength_min=0.08,
        news_liquidity_min=0.35,
        news_realized_vol_max=0.055,
        news_gap_cap_pct=7.5,
        news_rsi_max=72.0,
    ),
)


BALANCED_STYLE = RiskStyleProfile(
    name=RiskStyleName.BALANCED,
    description="Balanced research profile using the universe base configuration.",
    position_size_multiplier=1.0,
)


CONSERVATIVE_STYLE = RiskStyleProfile(
    name=RiskStyleName.CONSERVATIVE,
    description="Lower-turnover, lower-drawdown profile used as the production candidate.",
    position_size_multiplier=0.70,
)


AGGRESSIVE_STYLE = RiskStyleProfile(
    name=RiskStyleName.AGGRESSIVE,
    description="Research-only profile allowing broader setup participation and higher dispersion.",
    position_size_multiplier=1.15,
)


PROFILE_MAP = {
    UniverseName.DEFAULT: DEFAULT_PROFILE,
    UniverseName.NASDAQ100: NASDAQ100_PROFILE,
    UniverseName.SP500: SP500_PROFILE,
}

RISK_STYLE_MAP = {
    RiskStyleName.BALANCED: BALANCED_STYLE,
    RiskStyleName.CONSERVATIVE: CONSERVATIVE_STYLE,
    RiskStyleName.AGGRESSIVE: AGGRESSIVE_STYLE,
}


_TRACK_STRATEGY_MAP: dict[tuple[UniverseName, RiskStyleName], tuple[StrategyName, ...]] = {
    (UniverseName.NASDAQ100, RiskStyleName.BALANCED): (
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
    ),
    (UniverseName.NASDAQ100, RiskStyleName.CONSERVATIVE): (
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
        StrategyName.REVERSAL_CATALYST,
    ),
    (UniverseName.NASDAQ100, RiskStyleName.AGGRESSIVE): (
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
        StrategyName.GAP_AND_GO,
        StrategyName.SHORT_SQUEEZE,
        StrategyName.REVERSAL_CATALYST,
    ),
    (UniverseName.SP500, RiskStyleName.BALANCED): (
        StrategyName.GAP_AND_GO,
        StrategyName.PEAD,
    ),
    (UniverseName.SP500, RiskStyleName.CONSERVATIVE): (
        StrategyName.GAP_AND_GO,
        StrategyName.PEAD,
    ),
    (UniverseName.SP500, RiskStyleName.AGGRESSIVE): (
        StrategyName.GAP_AND_GO,
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.GAP_FILL,
        StrategyName.REVERSAL_CATALYST,
    ),
}


def get_universe_profile(name: UniverseName | str | None) -> UniverseStrategyProfile:
    try:
        normalized = UniverseName(str(name or UniverseName.DEFAULT.value).strip().upper())
    except ValueError:
        normalized = UniverseName.DEFAULT
    return PROFILE_MAP[normalized]


def get_risk_style(name: RiskStyleName | str | None) -> RiskStyleProfile:
    try:
        normalized = RiskStyleName(str(name or RiskStyleName.BALANCED.value).strip().upper())
    except ValueError:
        normalized = RiskStyleName.BALANCED
    return RISK_STYLE_MAP[normalized]


def resolve_universe_profile(ticker: str | None) -> UniverseStrategyProfile:
    normalized = (ticker or "").strip().upper()
    if not normalized:
        return DEFAULT_PROFILE
    if normalized in _load_universe_symbols("nasdaq100"):
        return NASDAQ100_PROFILE
    if normalized in _load_universe_symbols("sp500"):
        return SP500_PROFILE
    return DEFAULT_PROFILE


def get_supported_orchestrator_strategies() -> tuple[StrategyName, ...]:
    return SUPPORTED_ORCHESTRATOR_STRATEGIES


def get_allowed_strategies(profile: UniverseStrategyProfile) -> tuple[StrategyName, ...]:
    enabled = profile.strategy.enabled_strategies or SUPPORTED_ORCHESTRATOR_STRATEGIES
    return tuple(strategy for strategy in enabled if strategy in SUPPORTED_ORCHESTRATOR_STRATEGIES)


def validate_strategy_profile(profile: UniverseStrategyProfile) -> None:
    supported = set(SUPPORTED_ORCHESTRATOR_STRATEGIES)
    enabled = set(get_allowed_strategies(profile))
    invalid_priority = [strategy.value for strategy in profile.strategy.strategy_priority if strategy not in supported]
    invalid_enabled = [strategy.value for strategy in (profile.strategy.enabled_strategies or ()) if strategy not in supported]
    if invalid_priority or invalid_enabled:
        raise ValueError(
            "Universe profile references unsupported strategies: "
            f"priority={invalid_priority}, enabled={invalid_enabled}"
        )
    if enabled:
        missing_priority = [strategy.value for strategy in enabled if strategy not in profile.strategy.strategy_priority]
        if missing_priority:
            raise ValueError(f"Enabled strategies missing from priority ordering: {missing_priority}")


def validate_strategy_catalog() -> None:
    variants = [
        DEFAULT_PROFILE,
        compose_universe_profile(UniverseName.DEFAULT, RiskStyleName.BALANCED),
        compose_universe_profile(UniverseName.DEFAULT, RiskStyleName.CONSERVATIVE),
        compose_universe_profile(UniverseName.DEFAULT, RiskStyleName.AGGRESSIVE),
        compose_universe_profile(UniverseName.NASDAQ100, RiskStyleName.CONSERVATIVE),
        compose_universe_profile(UniverseName.NASDAQ100, RiskStyleName.AGGRESSIVE),
        compose_universe_profile(UniverseName.SP500, RiskStyleName.CONSERVATIVE),
        compose_universe_profile(UniverseName.SP500, RiskStyleName.AGGRESSIVE),
    ]
    for profile in variants:
        validate_strategy_profile(profile)


def compose_universe_profile(
    name: UniverseName | str | None,
    risk_style: RiskStyleName | str | None = None,
) -> UniverseStrategyProfile:
    base = get_universe_profile(name)
    style = _resolve_style_for_universe(base, risk_style)
    if style.name == RiskStyleName.BALANCED:
        profile = _apply_allowed_strategies(base, style.name)
        validate_strategy_profile(profile)
        return profile

    if base.name == UniverseName.NASDAQ100:
        profile = _compose_nasdaq_profile(base, style)
    elif base.name == UniverseName.SP500:
        profile = _compose_sp500_profile(base, style)
    else:
        profile = _compose_default_profile(base, style)
    validate_strategy_profile(profile)
    return profile


def _resolve_style_for_universe(
    base: UniverseStrategyProfile,
    risk_style: RiskStyleName | str | None,
) -> RiskStyleProfile:
    explicit = str(risk_style).strip() if risk_style is not None else ""
    if explicit:
        return get_risk_style(explicit)
    if base.name in {UniverseName.NASDAQ100, UniverseName.SP500}:
        return CONSERVATIVE_STYLE
    return BALANCED_STYLE


def _priority_for_allowed(base: tuple[StrategyName, ...], allowed: tuple[StrategyName, ...]) -> tuple[StrategyName, ...]:
    ordered = [strategy for strategy in base if strategy in allowed]
    for strategy in allowed:
        if strategy not in ordered:
            ordered.append(strategy)
    return tuple(ordered)


def _apply_allowed_strategies(base: UniverseStrategyProfile, style_name: RiskStyleName) -> UniverseStrategyProfile:
    allowed = _TRACK_STRATEGY_MAP.get((base.name, style_name))
    if allowed is None:
        return replace(base, risk_style_name=style_name)
    strategy = replace(
        base.strategy,
        strategy_priority=_priority_for_allowed(base.strategy.strategy_priority, allowed),
        enabled_strategies=allowed,
        allow_sentiment_only=StrategyName.SENTIMENT_ONLY in allowed,
    )
    return replace(base, strategy=strategy, risk_style_name=style_name)


def _compose_nasdaq_profile(base: UniverseStrategyProfile, style: RiskStyleProfile) -> UniverseStrategyProfile:
    if style.name == RiskStyleName.CONSERVATIVE:
        profile = replace(
            base,
            description=f"{base.description} Conservative overlay: only continuation strategies remain tradable.",
            gate=replace(
                base.gate,
                composite_threshold_delta=base.gate.composite_threshold_delta + 0.03,
                confidence_threshold_delta=base.gate.confidence_threshold_delta + 0.03,
                raw_score_threshold_delta=base.gate.raw_score_threshold_delta + 0.05,
                catalyst_volume_multiplier=base.gate.catalyst_volume_multiplier * 1.10,
                max_vix=26.0,
                blocked_regimes=("risk_off",),
            ),
            strategy=replace(
                base.strategy,
                news_volume_min=max(base.strategy.news_volume_min, 2.0),
                news_raw_min=max(base.strategy.news_raw_min, 0.68),
                news_price_change_min=max(base.strategy.news_price_change_min, 1.5),
                news_relative_strength_min=max(base.strategy.news_relative_strength_min, 0.06),
                news_liquidity_min=max(base.strategy.news_liquidity_min, 0.45),
                news_realized_vol_max=0.045,
                news_gap_cap_pct=8.0,
                news_rsi_max=72.0,
            ),
        )
        return _apply_allowed_strategies(profile, style.name)

    profile = replace(
        base,
        description=f"{base.description} Aggressive overlay: only selective reversal research setups remain after regime and sector quality filters.",
        gate=replace(
            base.gate,
            composite_threshold_delta=base.gate.composite_threshold_delta,
            confidence_threshold_delta=base.gate.confidence_threshold_delta,
            raw_score_threshold_delta=base.gate.raw_score_threshold_delta,
            catalyst_volume_multiplier=base.gate.catalyst_volume_multiplier,
            max_vix=32.0,
            blocked_regimes=("high_vol", "risk_off"),
        ),
        strategy=replace(
            base.strategy,
            gap_min_pct=max(2.3, base.strategy.gap_min_pct - 0.7),
            gap_raw_min=max(0.38, base.strategy.gap_raw_min - 0.08),
            gap_premarket_min=max(1.3, base.strategy.gap_premarket_min - 0.5),
            gap_price_change_min=max(0.0, base.strategy.gap_price_change_min - 0.25),
            gap_realized_vol_max=0.075,
            gap_rsi_max=82.0,
            gap_gap_cap_pct=14.0,
            gap_above_ma20_required=False,
            gap_quality_min=0.72,
            gap_volume_zscore_min=1.0,
            gap_earnings_surprise_min=6.0,
            gap_revision_min=1.0,
            gap_first5_green_required=False,
            news_volume_min=max(1.4, base.strategy.news_volume_min - 0.3),
            news_raw_min=max(0.56, base.strategy.news_raw_min - 0.06),
            news_price_change_min=max(0.5, base.strategy.news_price_change_min - 0.5),
            news_relative_strength_min=max(0.02, base.strategy.news_relative_strength_min - 0.02),
            news_liquidity_min=max(0.25, base.strategy.news_liquidity_min - 0.10),
            news_realized_vol_max=0.065,
            news_gap_cap_pct=12.0,
            news_rsi_max=80.0,
            news_quality_min=0.70,
            news_volume_zscore_min=1.0,
            news_earnings_surprise_min=6.0,
            news_revision_min=1.0,
            news_hours_max=24.0,
            news_distance_from_52w_high_min=-0.12,
            news_ma50_required=False,
        ),
    )
    return _apply_allowed_strategies(profile, style.name)


def _compose_sp500_profile(base: UniverseStrategyProfile, style: RiskStyleProfile) -> UniverseStrategyProfile:
    if style.name == RiskStyleName.CONSERVATIVE:
        profile = replace(
            base,
            description=f"{base.description} Conservative overlay: only the cleanest continuation setups remain.",
            gate=replace(
                base.gate,
                composite_threshold_delta=base.gate.composite_threshold_delta + 0.03,
                confidence_threshold_delta=base.gate.confidence_threshold_delta + 0.03,
                raw_score_threshold_delta=base.gate.raw_score_threshold_delta + 0.03,
                catalyst_volume_multiplier=base.gate.catalyst_volume_multiplier * 1.05,
                max_vix=24.0,
                blocked_regimes=("risk_off",),
            ),
            strategy=replace(
                base.strategy,
                gap_min_pct=max(base.strategy.gap_min_pct, 3.2),
                gap_raw_min=max(base.strategy.gap_raw_min, 0.50),
                gap_premarket_min=max(base.strategy.gap_premarket_min, 1.9),
                gap_relative_strength_min=max(base.strategy.gap_relative_strength_min, 0.03),
                gap_liquidity_min=max(base.strategy.gap_liquidity_min, 0.42),
                gap_price_change_min=max(base.strategy.gap_price_change_min, 0.55),
                gap_realized_vol_max=0.045,
                gap_rsi_max=68.0,
                gap_gap_cap_pct=6.5,
                gap_above_ma20_required=True,
                news_volume_min=max(base.strategy.news_volume_min, 2.5),
                news_raw_min=max(base.strategy.news_raw_min, 0.72),
                news_price_change_min=max(base.strategy.news_price_change_min, 1.2),
                news_relative_strength_min=max(base.strategy.news_relative_strength_min, 0.12),
                news_liquidity_min=max(base.strategy.news_liquidity_min, 0.45),
                news_realized_vol_max=0.045,
                news_gap_cap_pct=6.5,
                news_rsi_max=70.0,
            ),
        )
        return _apply_allowed_strategies(profile, style.name)

    profile = replace(
        base,
        description=f"{base.description} Aggressive overlay: only selective PEAD research setups remain after regime and sector quality filters.",
        gate=replace(
            base.gate,
            composite_threshold_delta=base.gate.composite_threshold_delta,
            confidence_threshold_delta=base.gate.confidence_threshold_delta,
            raw_score_threshold_delta=base.gate.raw_score_threshold_delta,
            catalyst_volume_multiplier=base.gate.catalyst_volume_multiplier,
            max_vix=29.0,
            blocked_regimes=("high_vol",),
        ),
        strategy=replace(
            base.strategy,
            gap_min_pct=max(2.0, base.strategy.gap_min_pct - 0.5),
            gap_raw_min=max(0.36, base.strategy.gap_raw_min - 0.06),
            gap_premarket_min=max(1.2, base.strategy.gap_premarket_min - 0.3),
            gap_price_change_min=max(0.0, base.strategy.gap_price_change_min - 0.15),
            gap_realized_vol_max=0.070,
            gap_rsi_max=74.0,
            gap_gap_cap_pct=9.0,
            gap_above_ma20_required=False,
            gap_quality_min=0.66,
            gap_volume_zscore_min=0.8,
            gap_earnings_surprise_min=4.0,
            gap_revision_min=0.5,
            gap_first5_green_required=False,
            news_volume_min=max(base.strategy.news_volume_min, 2.0),
            news_raw_min=max(base.strategy.news_raw_min, 0.62),
            news_price_change_min=max(base.strategy.news_price_change_min, 0.9),
            news_relative_strength_min=max(base.strategy.news_relative_strength_min, 0.08),
            news_liquidity_min=max(base.strategy.news_liquidity_min, 0.40),
            news_realized_vol_max=0.050,
            news_gap_cap_pct=7.0,
            news_rsi_max=72.0,
            news_quality_min=0.72,
            news_volume_zscore_min=1.0,
            news_earnings_surprise_min=5.0,
            news_revision_min=1.0,
            news_hours_max=18.0,
            news_distance_from_52w_high_min=-0.10,
            news_ma50_required=True,
        ),
    )
    return _apply_allowed_strategies(profile, style.name)


def _compose_default_profile(base: UniverseStrategyProfile, style: RiskStyleProfile) -> UniverseStrategyProfile:
    if style.name == RiskStyleName.CONSERVATIVE:
        profile = replace(
            base,
            gate=replace(
                base.gate,
                composite_threshold_delta=base.gate.composite_threshold_delta + 0.02,
                confidence_threshold_delta=base.gate.confidence_threshold_delta + 0.02,
                raw_score_threshold_delta=base.gate.raw_score_threshold_delta + 0.02,
                blocked_regimes=("risk_off",),
            ),
            strategy=replace(
                base.strategy,
                gap_price_change_min=max(base.strategy.gap_price_change_min, 0.4),
                gap_realized_vol_max=0.045,
                gap_rsi_max=70.0,
                gap_gap_cap_pct=7.0,
                gap_above_ma20_required=True,
                gap_quality_min=0.65,
                gap_volume_zscore_min=0.8,
                gap_earnings_surprise_min=4.0,
                gap_revision_min=0.5,
                news_volume_min=max(base.strategy.news_volume_min, 1.8),
                news_raw_min=max(base.strategy.news_raw_min, 0.55),
                news_quality_min=0.60,
                news_volume_zscore_min=0.8,
                news_earnings_surprise_min=4.0,
                news_revision_min=0.5,
                news_hours_max=36.0,
                news_distance_from_52w_high_min=-0.20,
                news_ma50_required=True,
                enabled_strategies=(
                    StrategyName.GAP_AND_GO,
                    StrategyName.NEWS_BREAKOUT,
                    StrategyName.PEAD,
                ),
                allow_sentiment_only=False,
            ),
        )
        return replace(profile, risk_style_name=style.name)

    profile = replace(
        base,
        gate=replace(
            base.gate,
            composite_threshold_delta=base.gate.composite_threshold_delta - 0.02,
            confidence_threshold_delta=base.gate.confidence_threshold_delta - 0.02,
            raw_score_threshold_delta=base.gate.raw_score_threshold_delta - 0.02,
            blocked_regimes=(),
        ),
        strategy=replace(
            base.strategy,
            gap_quality_min=max(base.strategy.gap_quality_min, 0.66),
            gap_volume_zscore_min=0.8,
            gap_earnings_surprise_min=3.0,
            gap_revision_min=0.5,
            news_quality_min=max(base.strategy.news_quality_min, 0.72),
            news_volume_zscore_min=1.0,
            news_earnings_surprise_min=4.0,
            news_revision_min=0.5,
            news_hours_max=24.0,
            news_ma50_required=True,
            enabled_strategies=(
                StrategyName.GAP_AND_GO,
                StrategyName.NEWS_BREAKOUT,
                StrategyName.PEAD,
                StrategyName.GAP_FILL,
                StrategyName.REVERSAL_CATALYST,
            ),
            allow_sentiment_only=False,
        ),
    )
    return replace(profile, risk_style_name=style.name)


@lru_cache(maxsize=4)
def _load_universe_symbols(universe_key: str) -> frozenset[str]:
    root = Path(__file__).resolve().parents[1]
    universe_dir = root / "data" / "universes"
    patterns = {
        "nasdaq100": ("nasdaq100_*.txt", "nasdaq100_*.json"),
        "sp500": ("sp500_*.txt", "sp500_*.json"),
    }
    selected_patterns = patterns.get(universe_key, ())
    symbols: set[str] = set()
    for pattern in selected_patterns:
        files = sorted(universe_dir.glob(pattern))
        for path in reversed(files):
            symbols.update(_read_symbol_file(path))
            if symbols:
                return frozenset(symbols)
    return frozenset()


def _read_symbol_file(path: Path) -> Iterable[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    if path.suffix.lower() == ".json":
        import json

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        tickers = payload.get("tickers", []) if isinstance(payload, dict) else []
        return [str(item).strip().upper() for item in tickers if str(item).strip()]

    return [line.strip().upper() for line in text.splitlines() if line.strip()]


__all__ = [
    "AGGRESSIVE_STYLE",
    "BALANCED_STYLE",
    "CONSERVATIVE_STYLE",
    "DEFAULT_PROFILE",
    "GateTuning",
    "NASDAQ100_PROFILE",
    "PROFILE_MAP",
    "RISK_STYLE_MAP",
    "RiskStyleName",
    "RiskStyleProfile",
    "SP500_PROFILE",
    "SUPPORTED_ORCHESTRATOR_STRATEGIES",
    "StrategyTuning",
    "UniverseName",
    "UniverseStrategyProfile",
    "compose_universe_profile",
    "get_allowed_strategies",
    "get_risk_style",
    "get_supported_orchestrator_strategies",
    "get_universe_profile",
    "resolve_universe_profile",
    "validate_strategy_catalog",
    "validate_strategy_profile",
]
