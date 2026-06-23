"""Investment-profile routing for universe/risk-style strategy recommendations."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

try:
    from core.universe_profiles import RiskStyleName, UniverseName, compose_universe_profile, get_allowed_strategies, get_risk_style
except ImportError:  # pragma: no cover
    from .universe_profiles import RiskStyleName, UniverseName, compose_universe_profile, get_allowed_strategies, get_risk_style


@dataclass(frozen=True)
class InvestmentProfile:
    code: str
    label_ko: str
    universe_profile: str
    risk_style: str
    description_ko: str
    redis_output_profile: str
    redis_channel_hint: str
    action_threshold_abs: float
    recommended_timeframe: str
    risk_controls: tuple[str, ...]

    @property
    def position_size_multiplier(self) -> float:
        return float(get_risk_style(self.risk_style).position_size_multiplier)

    @property
    def allowed_strategies(self) -> tuple[str, ...]:
        profile = compose_universe_profile(self.universe_profile, self.risk_style)
        return tuple(strategy.value for strategy in get_allowed_strategies(profile))

    def to_metadata(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label_ko": self.label_ko,
            "universe_profile": self.universe_profile,
            "risk_style": self.risk_style,
            "description_ko": self.description_ko,
            "redis_output_profile": self.redis_output_profile,
            "redis_channel_hint": self.redis_channel_hint,
            "action_threshold_abs": self.action_threshold_abs,
            "position_size_multiplier": self.position_size_multiplier,
            "recommended_timeframe": self.recommended_timeframe,
            "risk_controls": list(self.risk_controls),
            "allowed_strategies": list(self.allowed_strategies),
        }


_PROFILES: dict[str, InvestmentProfile] = {
    "NASDAQ100_AGGRESSIVE": InvestmentProfile(
        code="NASDAQ100_AGGRESSIVE",
        label_ko="나스닥 공격형",
        universe_profile=UniverseName.NASDAQ100.value,
        risk_style=RiskStyleName.AGGRESSIVE.value,
        description_ko="나스닥100 성장주에서 높은 변동성을 감수하고 단기 수익 기회를 추구합니다.",
        redis_output_profile="nasdaq100_aggressive_signal_v1",
        redis_channel_hint="trading-signals:nasdaq100:aggressive",
        action_threshold_abs=0.04,
        recommended_timeframe="intraday_to_3d",
        risk_controls=("research_only", "smaller_initial_stop", "sector_rotation_filter"),
    ),
    "NASDAQ100_CONSERVATIVE": InvestmentProfile(
        code="NASDAQ100_CONSERVATIVE",
        label_ko="나스닥 안정형",
        universe_profile=UniverseName.NASDAQ100.value,
        risk_style=RiskStyleName.CONSERVATIVE.value,
        description_ko="나스닥100 핵심 성장주의 실적 지속성과 제한된 품질 반전 전략을 선별합니다.",
        redis_output_profile="nasdaq100_conservative_signal_v1",
        redis_channel_hint="trading-signals:nasdaq100:conservative",
        action_threshold_abs=0.12,
        recommended_timeframe="2d_to_5d",
        risk_controls=("strict_execution_cost", "core_sector_filter", "extended_gap_block"),
    ),
    "SP500_AGGRESSIVE": InvestmentProfile(
        code="SP500_AGGRESSIVE",
        label_ko="S&P500 공격형",
        universe_profile=UniverseName.SP500.value,
        risk_style=RiskStyleName.AGGRESSIVE.value,
        description_ko="S&P500 종목에서 선별된 PEAD와 뉴스 돌파 전략을 적극적으로 활용합니다.",
        redis_output_profile="sp500_aggressive_signal_v1",
        redis_channel_hint="trading-signals:sp500:aggressive",
        action_threshold_abs=0.06,
        recommended_timeframe="1d_to_4d",
        risk_controls=("quality_pead_gate", "sector_cohort_filter", "news_freshness_filter"),
    ),
    "SP500_CONSERVATIVE": InvestmentProfile(
        code="SP500_CONSERVATIVE",
        label_ko="S&P500 안정형",
        universe_profile=UniverseName.SP500.value,
        risk_style=RiskStyleName.CONSERVATIVE.value,
        description_ko="S&P500의 실적 지속성과 낮은 실행 비용을 우선해 보수적으로 진입합니다.",
        redis_output_profile="sp500_conservative_signal_v1",
        redis_channel_hint="trading-signals:sp500:conservative",
        action_threshold_abs=0.10,
        recommended_timeframe="2d_to_5d",
        risk_controls=("strict_continuation_quality", "lower_vix_ceiling", "sector_gap_block"),
    ),
}

_ALIAS_MAP = {
    "NASDAQ_AGGRESSIVE": "NASDAQ100_AGGRESSIVE",
    "NASDAQ100_ATTACK": "NASDAQ100_AGGRESSIVE",
    "NASDAQ_ATTACK": "NASDAQ100_AGGRESSIVE",
    "NASDAQ100_CONSERVATIVE": "NASDAQ100_CONSERVATIVE",
    "NASDAQ_CONSERVATIVE": "NASDAQ100_CONSERVATIVE",
    "NASDAQ100_STABLE": "NASDAQ100_CONSERVATIVE",
    "NASDAQ_STABLE": "NASDAQ100_CONSERVATIVE",
    "SNP_AGGRESSIVE": "SP500_AGGRESSIVE",
    "SNP500_AGGRESSIVE": "SP500_AGGRESSIVE",
    "SP_AGGRESSIVE": "SP500_AGGRESSIVE",
    "SP500_ATTACK": "SP500_AGGRESSIVE",
    "SNP_CONSERVATIVE": "SP500_CONSERVATIVE",
    "SNP500_CONSERVATIVE": "SP500_CONSERVATIVE",
    "SNP_STABLE": "SP500_CONSERVATIVE",
    "SP_STABLE": "SP500_CONSERVATIVE",
    "SP500_STABLE": "SP500_CONSERVATIVE",
}


def resolve_investment_profile(
    investment_profile: str | None,
    *,
    universe_profile: str | None = None,
    risk_style: str | None = None,
) -> InvestmentProfile | None:
    key = _normalize_profile_key(investment_profile)
    if key is None and universe_profile:
        key = _normalize_profile_key(universe_profile)
    if key is None and universe_profile and risk_style:
        key = _normalize_profile_key(f"{universe_profile}_{risk_style}")
    if key is None:
        return None
    resolved = _ALIAS_MAP.get(key, key)
    return _PROFILES.get(resolved)


def build_strategy_recommendation(
    profile: InvestmentProfile,
    *,
    strategy: str | None,
    action: str,
    confidence: float | None,
    hold_days: int | None,
    risk_flags: list[str],
) -> dict[str, Any]:
    confidence_value = 0.0 if confidence is None else max(0.0, min(1.0, float(confidence)))
    return {
        "profile_code": profile.code,
        "profile_label_ko": profile.label_ko,
        "universe_profile": profile.universe_profile,
        "risk_style": profile.risk_style,
        "redis_output_profile": profile.redis_output_profile,
        "redis_channel_hint": profile.redis_channel_hint,
        "recommended_action": action,
        "recommended_strategy": strategy or "SENTIMENT_ONLY",
        "recommended_hold_days": hold_days,
        "confidence": round(confidence_value, 4),
        "action_threshold_abs": profile.action_threshold_abs,
        "position_size_multiplier": profile.position_size_multiplier,
        "recommended_timeframe": profile.recommended_timeframe,
        "risk_controls": list(profile.risk_controls),
        "allowed_strategies": list(profile.allowed_strategies),
        "risk_flags": list(risk_flags),
        "suitability_ko": profile.description_ko,
    }


def profile_action_from_score(raw_score: float, profile: InvestmentProfile | None) -> str:
    threshold = profile.action_threshold_abs if profile is not None else 0.05
    if raw_score > threshold:
        return "BUY"
    if raw_score < -threshold:
        return "SELL"
    return "HOLD"


def _normalize_profile_key(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    compact = raw.replace("&", "").replace(".", "")
    lower = compact.lower()
    if "나스닥" in raw:
        if "공격" in raw or "aggressive" in lower or "attack" in lower:
            return "NASDAQ100_AGGRESSIVE"
        if "안정" in raw or "보수" in raw or "conservative" in lower or "stable" in lower:
            return "NASDAQ100_CONSERVATIVE"
    if "snp" in lower or "s&p" in lower or "sp500" in lower or "snp500" in lower or "에스앤피" in raw:
        if "공격" in raw or "aggressive" in lower or "attack" in lower:
            return "SP500_AGGRESSIVE"
        if "안정" in raw or "보수" in raw or "conservative" in lower or "stable" in lower:
            return "SP500_CONSERVATIVE"
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", compact).strip("_").upper()
    normalized = normalized.replace("S_P_500", "SP500").replace("SNP500", "SP500").replace("SNP", "SP500")
    if normalized in _PROFILES:
        return normalized
    return _ALIAS_MAP.get(normalized, normalized)


__all__ = [
    "InvestmentProfile",
    "build_strategy_recommendation",
    "profile_action_from_score",
    "resolve_investment_profile",
]
