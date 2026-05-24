"""Shared track-specific strategy guardrails used by live analysis and research backtests."""

from __future__ import annotations

NASDAQ100_CONSERVATIVE_MAX_GAP_PCT = 8.0
NASDAQ100_CONSERVATIVE_CORE_SECTORS = frozenset({"TECHNOLOGY", "COMMUNICATION_SERVICES"})
NASDAQ100_CONSERVATIVE_QUALITY_REVERSAL_CAP_BUCKETS = frozenset({"MEGA"})
_NASDAQ100_CONSERVATIVE_QUALITY_REVERSAL_CAP_BUCKETS_NORMALIZED = frozenset(
    item.lower() for item in NASDAQ100_CONSERVATIVE_QUALITY_REVERSAL_CAP_BUCKETS
)

NASDAQ100_AGGRESSIVE_ALLOWED_STRATEGIES = frozenset({"REVERSAL_CATALYST"})
NASDAQ100_AGGRESSIVE_BLOCKED_SECTORS = frozenset(
    {
        "CONSUMER_CYCLICAL",
        "ENERGY",
        "INDUSTRIALS",
        "REAL_ESTATE",
        "UTILITIES",
    }
)
NASDAQ100_AGGRESSIVE_ROTATION_SECTORS = frozenset(
    {
        "BASIC_MATERIALS",
        "COMMUNICATION_SERVICES",
        "CONSUMER_DEFENSIVE",
    }
)

SP500_CONSERVATIVE_GAP_BLOCKED_SECTORS = frozenset({"UTILITIES"})
SP500_CONSERVATIVE_GAP_DEFAULT_COMPOSITE_FLOOR = 0.54
SP500_CONSERVATIVE_GAP_SECTOR_COMPOSITE_FLOORS = {
    "BASIC_MATERIALS": 0.56,
    "COMMUNICATION_SERVICES": 0.56,
    "CONSUMER_CYCLICAL": 0.54,
    "REAL_ESTATE": 0.58,
}

SP500_AGGRESSIVE_ALLOWED_STRATEGIES = frozenset({"PEAD"})
SP500_AGGRESSIVE_BLOCKED_SECTORS = frozenset({"HEALTHCARE", "INDUSTRIALS"})


def normalize_sector_code(sector_code: str | None) -> str:
    return str(sector_code or "").strip().upper()


def normalize_strategy_code(strategy_code: str | None) -> str:
    return str(strategy_code or "").strip().upper()


def nasdaq100_conservative_gap_extended(gap_pct: float | None) -> bool:
    try:
        numeric = abs(float(gap_pct or 0.0))
    except (TypeError, ValueError):
        return False
    return numeric >= NASDAQ100_CONSERVATIVE_MAX_GAP_PCT


def nasdaq100_conservative_sector_allowed(sector_code: str | None) -> bool:
    sector = normalize_sector_code(sector_code)
    if not sector:
        return True
    return sector in NASDAQ100_CONSERVATIVE_CORE_SECTORS


def nasdaq100_conservative_high_vol_news_blocked(strategy_code: str | None, regime: str | None) -> bool:
    return normalize_strategy_code(strategy_code) == "NEWS_BREAKOUT" and str(regime or "").strip().lower() == "high_vol"


def normalize_market_cap_bucket(market_cap_bucket: str | None) -> str:
    return str(market_cap_bucket or "").strip().lower()


def nasdaq100_conservative_quality_reversal_allowed(
    *,
    sector_code: str | None,
    market_cap_bucket: str | None,
    regime: str | None,
) -> bool:
    return (
        nasdaq100_conservative_sector_allowed(sector_code)
        and normalize_market_cap_bucket(market_cap_bucket) in _NASDAQ100_CONSERVATIVE_QUALITY_REVERSAL_CAP_BUCKETS_NORMALIZED
        and str(regime or "").strip().lower() == "normal"
    )


def nasdaq100_aggressive_strategy_allowed(strategy_code: str | None) -> bool:
    return normalize_strategy_code(strategy_code) in NASDAQ100_AGGRESSIVE_ALLOWED_STRATEGIES


def nasdaq100_aggressive_sector_blocked(sector_code: str | None) -> bool:
    return normalize_sector_code(sector_code) in NASDAQ100_AGGRESSIVE_BLOCKED_SECTORS


def nasdaq100_aggressive_rotation_allowed(sector_code: str | None) -> bool:
    return normalize_sector_code(sector_code) in NASDAQ100_AGGRESSIVE_ROTATION_SECTORS


def sp500_conservative_gap_sector_blocked(sector_code: str | None) -> bool:
    return normalize_sector_code(sector_code) in SP500_CONSERVATIVE_GAP_BLOCKED_SECTORS


def sp500_conservative_gap_composite_floor(sector_code: str | None) -> float:
    sector = normalize_sector_code(sector_code)
    return float(SP500_CONSERVATIVE_GAP_SECTOR_COMPOSITE_FLOORS.get(sector, SP500_CONSERVATIVE_GAP_DEFAULT_COMPOSITE_FLOOR))


def sp500_aggressive_strategy_allowed(strategy_code: str | None) -> bool:
    return normalize_strategy_code(strategy_code) in SP500_AGGRESSIVE_ALLOWED_STRATEGIES


def sp500_aggressive_sector_blocked(sector_code: str | None) -> bool:
    return normalize_sector_code(sector_code) in SP500_AGGRESSIVE_BLOCKED_SECTORS


__all__ = [
    "NASDAQ100_AGGRESSIVE_ALLOWED_STRATEGIES",
    "NASDAQ100_AGGRESSIVE_BLOCKED_SECTORS",
    "NASDAQ100_AGGRESSIVE_ROTATION_SECTORS",
    "NASDAQ100_CONSERVATIVE_CORE_SECTORS",
    "NASDAQ100_CONSERVATIVE_MAX_GAP_PCT",
    "NASDAQ100_CONSERVATIVE_QUALITY_REVERSAL_CAP_BUCKETS",
    "nasdaq100_conservative_quality_reversal_allowed",
    "nasdaq100_conservative_high_vol_news_blocked",
    "nasdaq100_conservative_sector_allowed",
    "normalize_market_cap_bucket",
    "nasdaq100_aggressive_rotation_allowed",
    "nasdaq100_aggressive_sector_blocked",
    "nasdaq100_aggressive_strategy_allowed",
    "nasdaq100_conservative_gap_extended",
    "normalize_strategy_code",
    "SP500_CONSERVATIVE_GAP_BLOCKED_SECTORS",
    "SP500_CONSERVATIVE_GAP_DEFAULT_COMPOSITE_FLOOR",
    "SP500_CONSERVATIVE_GAP_SECTOR_COMPOSITE_FLOORS",
    "SP500_AGGRESSIVE_ALLOWED_STRATEGIES",
    "SP500_AGGRESSIVE_BLOCKED_SECTORS",
    "normalize_sector_code",
    "sp500_aggressive_sector_blocked",
    "sp500_aggressive_strategy_allowed",
    "sp500_conservative_gap_composite_floor",
    "sp500_conservative_gap_sector_blocked",
]
