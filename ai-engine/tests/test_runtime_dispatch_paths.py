from __future__ import annotations

import asyncio
import pytest
from config import Settings
from services.runtime_dispatch_service import dispatch_analysis

from models.request_models import AnalyzeRequest, MarketData, SectionType, SourceType
from models.signal_models import GeminiAnalysisResult
from src.graph.nodes.analyze import analysis_node

import main


async def _fake_run_analysis(**kwargs):
    assert kwargs["ticker"] == "NVDA"
    assert kwargs["current_chunk"]
    assert kwargs["section_type"] == SectionType.GUIDANCE
    assert kwargs["source_type"] == SourceType.EARNINGS_CALL
    return GeminiAnalysisResult(
        direction="LONG",
        magnitude=0.8,
        confidence=0.77,
        rationale="guidance improved",
        catalyst_type="GUIDANCE_UP",
        strategy="PEAD",
        metadata={"signal_explanation": {"summary_short": "가이던스 상향"}},
    )


def test_dispatch_analysis_serializes_result(monkeypatch):
    monkeypatch.setattr(main.app.state.analysis_service, "analyze", _fake_run_analysis)
    payload = AnalyzeRequest(
        ticker="NVDA",
        prompt="guidance raised and demand improved",
        market_data=MarketData(ticker="NVDA"),
        section_type=SectionType.GUIDANCE,
        source_type=SourceType.EARNINGS_CALL,
        chunk_sequence=1,
        request_priority=7,
        is_final=False,
        route_profile="standard",
    )

    result = asyncio.run(main._dispatch_analysis(payload, main.get_settings()))
    assert result["strategy"] == "PEAD"
    assert result["analysis"]["strategy"] == "PEAD"
    assert result["metadata"]["signal_explanation"]["summary_short"] == "가이던스 상향"


def test_create_app_dispatch_uses_local_analysis_service(monkeypatch):
    local_app = main.create_app()

    async def _local_analyze(**kwargs):
        return GeminiAnalysisResult(
            direction="LONG",
            magnitude=0.5,
            confidence=0.8,
            rationale="local-app",
            catalyst_type="GUIDANCE_UP",
            strategy="PEAD",
            metadata={},
        )

    async def _global_analyze(**kwargs):
        return GeminiAnalysisResult(
            direction="SHORT",
            magnitude=0.5,
            confidence=0.8,
            rationale="global-app",
            catalyst_type="GUIDANCE_DOWN",
            strategy="GAP_FILL",
            metadata={},
        )

    monkeypatch.setattr(local_app.state.analysis_service, "analyze", _local_analyze)
    monkeypatch.setattr(main.app.state.analysis_service, "analyze", _global_analyze)

    payload = AnalyzeRequest(
        ticker="NVDA",
        prompt="guidance raised and demand improved",
        market_data=MarketData(ticker="NVDA"),
        section_type=SectionType.GUIDANCE,
        source_type=SourceType.EARNINGS_CALL,
        chunk_sequence=1,
        request_priority=7,
        is_final=False,
        route_profile="standard",
    )

    result = asyncio.run(local_app.state.dispatch_analysis(payload))
    assert result["analysis"]["rationale"] == "local-app"
    assert result["strategy"] == "PEAD"


def test_analysis_node_uses_runtime_schema(monkeypatch):
    monkeypatch.setattr("src.graph.nodes.analyze.run_analysis", _fake_run_analysis)
    state = {
        "ticker": "NVDA",
        "transcript_chunk": "guidance raised and demand improved",
        "market_data": {"ticker": "NVDA"},
        "section_type": "GUIDANCE",
        "source_type": "EARNINGS_CALL",
        "chunk_sequence": 1,
        "request_priority": 7,
    }

    result = asyncio.run(analysis_node(state))
    assert result["strategy"] == "PEAD"
    assert result["analysis"]["direction"] == "LONG"


def test_required_control_failure_blocks_signal_without_losing_analysis():
    class UnavailableControls:
        def apply_runtime_controls(self, **kwargs):
            raise RuntimeError("database unavailable")

    payload = AnalyzeRequest(ticker="NVDA", current_chunk="guidance raised", market_data=MarketData(ticker="NVDA"),
                             section_type=SectionType.GUIDANCE, source_type=SourceType.EARNINGS_CALL)
    result = asyncio.run(dispatch_analysis(payload=payload, settings=Settings(_env_file=None),
                         analysis_runner=_fake_run_analysis, control_service=UnavailableControls()))
    assert result["analysis"]["rationale"] == "guidance improved"
    assert result["analysis"]["execution_allowed"] is False
    assert result["analysis"]["decision_state"] == "blocked"
    assert result["signal_brief"]["action"] == "AVOID"
    assert result["signal_brief"]["summary_ko"].startswith("진입 보류.")
    assert result["signal_brief"]["execution_badge"]["label"] == "실행 차단"
    assert result["data"]["signal_brief"] == result["signal_brief"]
    assert result["metadata"]["runtime_controls"]["status"] == "unavailable"
    hero = next(c for c in result["data"]["cards"] if c["card_type"] == "hero_decision")
    assert hero["payload"]["execution_allowed"] is False
    assert hero["payload"]["decision"] == "AVOID"
    assert hero["payload"]["summary"] == result["signal_brief"]["summary_ko"]
    assert hero["payload"]["badge"] == "blocked"


def test_explicit_offline_mode_skips_controls_and_is_not_production_valid():
    class MustNotCall:
        def apply_runtime_controls(self, **kwargs):
            raise AssertionError("offline mode must not call controls")

    settings = Settings(_env_file=None, RUNTIME_CONTROLS_MODE="offline")
    payload = AnalyzeRequest(ticker="NVDA", current_chunk="guidance raised", market_data=MarketData(ticker="NVDA"),
                             section_type=SectionType.GUIDANCE, source_type=SourceType.EARNINGS_CALL)
    result = asyncio.run(dispatch_analysis(payload=payload, settings=settings,
                         analysis_runner=_fake_run_analysis, control_service=MustNotCall()))
    assert result["metadata"]["runtime_controls"] == {"status": "offline", "verified": False}
    with pytest.raises(ValueError, match="not permitted in prod"):
        Settings(_env_file=None, environment="prod", RUNTIME_CONTROLS_MODE="offline")
