from __future__ import annotations

from core.universe_profiles import (
    compose_universe_profile,
    get_allowed_strategies,
    validate_strategy_catalog,
)
from models.signal_models import StrategyName


def test_strategy_catalog_only_references_supported_orchestrator_strategies() -> None:
    validate_strategy_catalog()


def test_nasdaq100_conservative_strategy_set_matches_v955_plan() -> None:
    profile = compose_universe_profile("NASDAQ100", "CONSERVATIVE")
    assert get_allowed_strategies(profile) == (
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.MOMENTUM_CARRY,
        StrategyName.REVERSAL_CATALYST,
    )


def test_sp500_aggressive_strategy_set_matches_v94_plan() -> None:
    profile = compose_universe_profile("SP500", "AGGRESSIVE")
    assert get_allowed_strategies(profile) == (
        StrategyName.GAP_AND_GO,
        StrategyName.PEAD,
        StrategyName.NEWS_BREAKOUT,
        StrategyName.GAP_FILL,
        StrategyName.REVERSAL_CATALYST,
    )
