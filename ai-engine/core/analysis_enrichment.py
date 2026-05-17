"""Post-LLM enrichment pipeline for strategy, explanation, and product payloads."""

from __future__ import annotations

import logging

try:
    from core.decision_assistant import build_decision_assistant
    from core.institutional_edge import build_institutional_edge
    from core.options_advisor import build_options_advice
    from core.product_surface import build_product_surface
    from core.signal_explainer import build_signal_explanation
    from core.trade_plan import build_trade_plan
    from models.request_models import MarketData, SectionType, SourceType
    from models.signal_models import GeminiAnalysisResult
    from strategies.orchestrator import choose_strategy
except ImportError:  # pragma: no cover
    from .decision_assistant import build_decision_assistant
    from .institutional_edge import build_institutional_edge
    from .options_advisor import build_options_advice
    from .product_surface import build_product_surface
    from .signal_explainer import build_signal_explanation
    from .trade_plan import build_trade_plan
    from ..models.request_models import MarketData, SectionType, SourceType
    from ..models.signal_models import GeminiAnalysisResult
    from ..strategies.orchestrator import choose_strategy


logger = logging.getLogger(__name__)


class AnalysisEnrichmentPipeline:
    """Apply deterministic post-analysis enrichments in one ordered boundary."""

    def enrich(
        self,
        *,
        market_data: MarketData,
        analysis: GeminiAnalysisResult,
        section_type: SectionType,
        source_type: SourceType,
        universe_profile: str | None = None,
    ) -> GeminiAnalysisResult:
        strategy_decision = choose_strategy(
            market_data,
            gemini_result=analysis,
            section_type=section_type,
            universe_profile=universe_profile,
        )
        analysis.strategy = strategy_decision.strategy.value
        analysis.hold_days = strategy_decision.hold_days
        analysis.risk_flags.extend(flag for flag in strategy_decision.risk_flags if flag not in analysis.risk_flags)
        analysis.metadata.update(strategy_decision.metadata)

        trade_plan = build_trade_plan(market_data, strategy_decision, analysis)
        analysis.metadata["trade_plan"] = trade_plan

        options_advice = build_options_advice(market_data, strategy_decision, analysis)
        if options_advice is not None:
            analysis.metadata["options_advice"] = options_advice

        signal_explanation = build_signal_explanation(
            market_data=market_data,
            analysis=analysis,
            strategy_decision=strategy_decision,
            section_type=section_type,
            source_type=source_type,
        )
        analysis.signal_explanation = signal_explanation.get("display_text")
        analysis.hold_days_reason = signal_explanation.get("hold_period_reason")
        analysis.metadata["signal_explanation"] = signal_explanation

        product_surface = build_product_surface(
            market_data=market_data,
            analysis=analysis,
            strategy_decision=strategy_decision,
            source_type=source_type,
            signal_explanation=signal_explanation,
            trade_plan=trade_plan,
            options_advice=options_advice,
        )
        institutional_edge = self._build_institutional_edge(
            market_data=market_data,
            analysis=analysis,
            strategy_decision=strategy_decision,
            source_type=source_type,
            signal_explanation=signal_explanation,
            trade_plan=trade_plan,
            product_surface=product_surface,
        )
        product_surface["institutional_edge"] = institutional_edge
        self._attach_institutional_edge_to_frontend(product_surface, institutional_edge)
        decision_assistant = self._build_decision_assistant(
            market_data=market_data,
            analysis=analysis,
            strategy_decision=strategy_decision,
            source_type=source_type,
            signal_explanation=signal_explanation,
            trade_plan=trade_plan,
            product_surface=product_surface,
        )
        product_surface["decision_assistant"] = decision_assistant
        self._attach_decision_assistant_to_frontend(product_surface, decision_assistant)

        analysis.metadata["institutional_edge"] = institutional_edge
        analysis.metadata["decision_assistant"] = decision_assistant
        analysis.metadata["product_surface"] = product_surface
        return analysis

    @staticmethod
    def _attach_institutional_edge_to_frontend(
        product_surface: dict,
        institutional_edge: dict,
    ) -> None:
        front_payload = product_surface.get("front_payload_ko")
        if isinstance(front_payload, dict):
            front_payload["institutional_edge"] = institutional_edge.get("frontend", institutional_edge)
        frontend_contract = product_surface.get("frontend_contract_ko")
        if isinstance(frontend_contract, dict):
            frontend_contract["institutional_edge"] = institutional_edge.get("frontend", institutional_edge)

    @staticmethod
    def _attach_decision_assistant_to_frontend(
        product_surface: dict,
        decision_assistant: dict,
    ) -> None:
        frontend_payload = decision_assistant.get("frontend_cards", decision_assistant)
        front_payload = product_surface.get("front_payload_ko")
        if isinstance(front_payload, dict):
            front_payload["decision_assistant"] = frontend_payload
        frontend_contract = product_surface.get("frontend_contract_ko")
        if isinstance(frontend_contract, dict):
            frontend_contract["decision_assistant"] = frontend_payload

    @staticmethod
    def _build_institutional_edge(
        *,
        market_data: MarketData,
        analysis: GeminiAnalysisResult,
        strategy_decision,
        source_type: SourceType,
        signal_explanation: dict,
        trade_plan: dict | None,
        product_surface: dict | None,
    ) -> dict:
        try:
            return build_institutional_edge(
                market_data=market_data,
                analysis=analysis,
                strategy_decision=strategy_decision,
                source_type=source_type,
                signal_explanation=signal_explanation,
                trade_plan=trade_plan,
                product_surface=product_surface,
            )
        except Exception as exc:
            logger.warning("Institutional edge package failed: %s", exc)
            return {
                "schema_version": "2026-04-26.institutional-edge.v1",
                "institutional_grade_score": 0.0,
                "grade": "E",
                "approval_state": "research_only",
                "blockers": ["institutional_edge_generation_failed"],
                "error": str(exc)[:240],
            }

    @staticmethod
    def _build_decision_assistant(
        *,
        market_data: MarketData,
        analysis: GeminiAnalysisResult,
        strategy_decision,
        source_type: SourceType,
        signal_explanation: dict,
        trade_plan: dict | None,
        product_surface: dict | None,
    ) -> dict:
        try:
            return build_decision_assistant(
                market_data=market_data,
                analysis=analysis,
                strategy_decision=strategy_decision,
                source_type=source_type,
                signal_explanation=signal_explanation,
                trade_plan=trade_plan,
                product_surface=product_surface,
            )
        except Exception as exc:
            logger.warning("Decision assistant package failed: %s", exc)
            return {
                "schema_version": "2026-05-03.decision-assistant.v1",
                "sell_first": {
                    "action": "HOLD",
                    "recommended_change_pct": 0.0,
                    "position_intent_ko": "판단 보조 모듈 실패로 기본 관망 처리",
                    "reason_bullets": ["decision_assistant_generation_failed"],
                    "risk_flags": ["decision_assistant_generation_failed"],
                },
                "no_trade_explainer": {
                    "blocked": True,
                    "deny_summary_ko": "판단 보조 모듈 실패로 신규 진입을 보류합니다.",
                    "blocked_reasons": ["decision_assistant_generation_failed"],
                    "what_to_wait_for": ["모듈 로그 확인 후 재분석"],
                },
                "error": str(exc)[:240],
            }


__all__ = ["AnalysisEnrichmentPipeline"]
