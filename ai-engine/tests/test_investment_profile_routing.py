from __future__ import annotations

from core.investment_profiles import profile_action_from_score, resolve_investment_profile
from models.legacy_contract_models import LegacyAnalyzeRequest
from services.legacy_contract_adapter import LegacyContractAdapter


def test_investment_profile_aliases_cover_four_user_profiles() -> None:
    cases = {
        "NASDAQ100_AGGRESSIVE": ("NASDAQ100_AGGRESSIVE", "NASDAQ100", "AGGRESSIVE"),
        "NASDAQ100_CONSERVATIVE": ("NASDAQ100_CONSERVATIVE", "NASDAQ100", "CONSERVATIVE"),
        "SNP_AGGRESSIVE": ("SP500_AGGRESSIVE", "SP500", "AGGRESSIVE"),
        "SNP_CONSERVATIVE": ("SP500_CONSERVATIVE", "SP500", "CONSERVATIVE"),
    }
    for raw, expected in cases.items():
        profile = resolve_investment_profile(raw)
        assert profile is not None
        assert (profile.code, profile.universe_profile, profile.risk_style) == expected
        assert profile.redis_output_profile
        assert profile.allowed_strategies


def test_profile_action_thresholds_differ_by_risk_style() -> None:
    aggressive = resolve_investment_profile("NASDAQ100_AGGRESSIVE")
    conservative = resolve_investment_profile("NASDAQ100_CONSERVATIVE")
    assert aggressive is not None and conservative is not None

    assert profile_action_from_score(0.06, aggressive) == "BUY"
    assert profile_action_from_score(0.06, conservative) == "HOLD"


def test_legacy_adapter_maps_investment_profile_into_request() -> None:
    payload = LegacyAnalyzeRequest(
        ticker="NVDA",
        text_chunk="Management raised guidance.",
        investment_profile="SNP_CONSERVATIVE",
    )

    request = LegacyContractAdapter.to_analyze_request(payload)

    assert request.investment_profile == "SNP_CONSERVATIVE"
    assert request.request_metadata["investment_profile"] == "SNP_CONSERVATIVE"


def test_legacy_redis_output_is_profile_specific() -> None:
    payload = LegacyAnalyzeRequest(
        ticker="NVDA",
        text_chunk="Management raised guidance.",
        timestamp=1778600000,
        investment_profile="NASDAQ100_AGGRESSIVE",
    )
    envelope = {
        "analysis": {
            "direction": "BULLISH",
            "magnitude": 0.06,
            "confidence": 0.72,
            "rationale": "Guidance improved.",
            "strategy": "NEWS_BREAKOUT",
            "hold_days": 3,
            "risk_flags": [],
            "metadata": {
                    "investment_profile": resolve_investment_profile("NASDAQ100_AGGRESSIVE").to_metadata(),
            },
        },
        "data": {"event": {"event_id": "evt_1"}},
    }

    signal = LegacyContractAdapter.to_legacy_signal(payload, envelope)

    assert signal.action == "BUY"
    assert signal.investment_profile == "NASDAQ100_AGGRESSIVE"
    assert signal.investment_profile_label_ko == "??? ???"
    assert signal.universe_profile == "NASDAQ100"
    assert signal.risk_style == "AGGRESSIVE"
    assert signal.redis_output_profile == "nasdaq100_aggressive_signal_v1"
    assert signal.strategy_recommendation is not None
    assert signal.strategy_recommendation["redis_channel_hint"] == "trading-signals:nasdaq100:aggressive"


def test_conservative_redis_output_holds_weak_profile_score() -> None:
    payload = LegacyAnalyzeRequest(
        ticker="NVDA",
        text_chunk="Management raised guidance.",
        timestamp=1778600000,
        investment_profile="NASDAQ100_CONSERVATIVE",
    )
    envelope = {
        "analysis": {
            "direction": "BULLISH",
            "magnitude": 0.06,
            "confidence": 0.72,
            "rationale": "Guidance improved.",
            "strategy": "NEWS_BREAKOUT",
            "hold_days": 3,
            "risk_flags": [],
            "metadata": {
                    "investment_profile": resolve_investment_profile("NASDAQ100_CONSERVATIVE").to_metadata(),
            },
        }
    }

    signal = LegacyContractAdapter.to_legacy_signal(payload, envelope)

    assert signal.action == "HOLD"
    assert signal.investment_profile == "NASDAQ100_CONSERVATIVE"
    assert signal.redis_output_profile == "nasdaq100_conservative_signal_v1"
    assert signal.strategy_recommendation["action_threshold_abs"] == 0.12
