from __future__ import annotations

import logging

try:
    from config import get_settings
    from core.analysis_enrichment import AnalysisEnrichmentPipeline
    from core.context_manager import ChunkRecord, RollingContextManager
    from core.gemini_client import gemini_client
    from core.llm_router import decide_route
    from core.external_retriever import external_retriever
    from core.phase1_scorer import score_phase1
    from core.prompt_builder import build_prompt
    from core.signal_data_hub import SignalDataHub
    from core.token_budgeter import TokenBudgeter, TokenUsageEvent, estimate_tokens
    from core.transcript_signal_enhancer import TranscriptSignalEnhancer
    from models.canonical_models import CanonicalEventBundle, CanonicalSourceHealth
    from models.evidence_models import EvidenceDocument
    from models.request_models import MarketData, SectionType, SourceType
    from models.signal_models import GeminiAnalysisResult
    from services.canonical_bundle_service import CanonicalBundleService, SourceHealthTelemetry
    from services.evidence_retrieval_service import EvidenceRetrievalService
except ImportError:  # pragma: no cover
    from ..config import get_settings
    from .analysis_enrichment import AnalysisEnrichmentPipeline
    from .context_manager import ChunkRecord, RollingContextManager
    from .gemini_client import gemini_client
    from .llm_router import decide_route
    from .external_retriever import external_retriever
    from .phase1_scorer import score_phase1
    from .prompt_builder import build_prompt
    from .signal_data_hub import SignalDataHub
    from .token_budgeter import TokenBudgeter, TokenUsageEvent, estimate_tokens
    from .transcript_signal_enhancer import TranscriptSignalEnhancer
    from ..models.canonical_models import CanonicalEventBundle, CanonicalSourceHealth
    from ..models.evidence_models import EvidenceDocument
    from ..models.request_models import MarketData, SectionType, SourceType
    from ..models.signal_models import GeminiAnalysisResult
    from ..services.canonical_bundle_service import CanonicalBundleService, SourceHealthTelemetry
    from ..services.evidence_retrieval_service import EvidenceRetrievalService

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self, **_: object) -> None:
        self.context_manager = RollingContextManager(max_chunks=5)
        self.transcript_enhancer = TranscriptSignalEnhancer()
        self.canonical_bundle_service = CanonicalBundleService()
        self.evidence_service = EvidenceRetrievalService()
        self.external_retriever = external_retriever
        self.route_counts: dict[str, int] = {}
        self.source_health_telemetry = SourceHealthTelemetry()
        self.signal_data_hub = SignalDataHub()
        self.token_budgeter = TokenBudgeter()
        self.enrichment_pipeline = AnalysisEnrichmentPipeline()

    @staticmethod
    def _fallback_result(
        *,
        ticker: str,
        route_profile: str,
        model_route: str,
        source_type: SourceType,
        chunk_sequence: int,
        detail: str,
    ) -> GeminiAnalysisResult:
        return GeminiAnalysisResult(
            direction="NEUTRAL",
            magnitude=0.0,
            confidence=0.0,
            rationale="LLM response validation failed; neutral fallback applied.",
            catalyst_type="UNCLASSIFIED",
            euphemism_count=0,
            negative_word_ratio=0.0,
            cot_reasoning="fallback",
            model_route=model_route,
            route_profile=route_profile,
            source_type=source_type.value,
            chunk_sequence=chunk_sequence,
            metadata={
                "llm_error": {
                    "ticker": ticker,
                    "stage": "response_parse_or_schema_validation",
                    "detail": detail[:400],
                }
            },
        )

    async def analyze(
        self,
        *,
        ticker: str,
        current_chunk: str,
        market_data: MarketData,
        section_type: SectionType,
        source_type: SourceType,
        chunk_sequence: int,
        request_priority: int,
        is_final: bool,
        route_profile: str | None = None,
        universe_profile: str | None = None,
        canonical_bundle: CanonicalEventBundle | None = None,
        source_health: list[CanonicalSourceHealth] | None = None,
        evidence_documents: list[EvidenceDocument] | None = None,
        request_metadata: dict[str, object] | None = None,
    ) -> GeminiAnalysisResult:
        settings = get_settings()
        feature_bundle = self.canonical_bundle_service.build_feature_bundle(
            ticker=ticker,
            market_data=market_data,
            current_chunk=current_chunk,
            canonical_bundle=canonical_bundle,
            source_health=source_health,
        )
        self.source_health_telemetry.record(feature_bundle)
        data_hub_receipt = self.signal_data_hub.record_feature_bundle(
            ticker=ticker,
            feature_bundle=feature_bundle,
        )
        evidence_result = self.evidence_service.retrieve_for_analysis(
            ticker=ticker,
            current_chunk=current_chunk,
            source_type=source_type,
            market_data=market_data,
            canonical_bundle=canonical_bundle,
            source_health=source_health,
            request_metadata=dict(request_metadata or {}),
            evidence_documents=evidence_documents,
        )
        external_documents = self.external_retriever.retrieve(
            query=f"{ticker} {current_chunk}",
            ticker=ticker,
            chunk_timestamp=int((request_metadata or {}).get("timestamp") or 0),
            preferred_sources=[],
            lookback_days=int(getattr(settings, "rag_external_default_lookback_days", 30)),
            limit=int(getattr(settings, "rag_top_k", 5)),
        )
        external_context = self._external_evidence_context(external_documents)
        evidence_context = evidence_result.evidence_context
        if external_context:
            evidence_context = f"{external_context}\n\n{evidence_context}" if evidence_context else external_context
        phase1 = score_phase1(
            current_chunk=current_chunk,
            market_data=market_data,
            section_type=section_type,
            source_type=source_type,
        )
        context_chunks = self.context_manager.get(ticker)
        route_decision = decide_route(
            current_chunk=current_chunk,
            context_chunks=context_chunks,
            market_data=market_data,
            section_type=section_type,
            request_priority=request_priority,
            is_final=is_final,
            phase1_raw_score=phase1.raw_score,
        )
        effective_profile = route_profile or route_decision.route_profile
        self.route_counts[route_decision.model] = self.route_counts.get(route_decision.model, 0) + 1

        prompt = build_prompt(
            ticker=ticker,
            current_chunk=current_chunk,
            context_chunks=context_chunks,
            market_data=market_data,
            section_type=section_type.value,
            source_type=source_type.value,
            route_profile=effective_profile,
            context_policy=route_decision.context_policy,
            phase1_score=phase1.raw_score,
            feature_bundle_context=feature_bundle.get("prompt_context"),
            evidence_context=evidence_context,
        )
        usage = await gemini_client.generate_content_with_metadata(
            model=route_decision.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": settings.gemini_temperature,
                "max_output_tokens": route_decision.max_output_tokens,
                "route_profile": effective_profile,
            },
        )
        try:
            parsed_dict = gemini_client.parse_response_text(usage.text)
            parsed = GeminiAnalysisResult.model_validate(parsed_dict)
        except Exception as exc:
            logger.warning(
                "Neutral fallback applied for %s chunk %s after invalid LLM response: %s",
                ticker,
                chunk_sequence,
                exc,
            )
            parsed = self._fallback_result(
                ticker=ticker,
                route_profile=effective_profile,
                model_route=route_decision.model,
                source_type=source_type,
                chunk_sequence=chunk_sequence,
                detail=str(exc),
            )
        parsed.route_profile = effective_profile
        parsed.model_route = route_decision.model
        parsed.source_type = source_type.value
        parsed.chunk_sequence = chunk_sequence
        parsed.metadata.update(
            {
                "phase1": {"raw_score": phase1.raw_score, "confidence": phase1.confidence, "label": phase1.label, "provider": phase1.provider, "rationale_hint": phase1.rationale_hint},
                "router": {
                    "context_policy": route_decision.context_policy,
                    "novelty": round(route_decision.novelty, 4),
                    "primary_model": route_decision.primary_model,
                },
                "feature_bundle": feature_bundle,
                "source_health_summary": feature_bundle.get("source_health_summary"),
                "evidence_retrieval": evidence_result.model_dump(mode="json"),
                "external_rag": {
                    "has_external_evidence": bool(external_documents),
                    "evidence_count": len(external_documents),
                    "documents": [
                        {
                            "doc_id": item.doc_id,
                            "title": item.title,
                            "source_type": item.source_type,
                            "published_at": item.published_at,
                            "score": item.score,
                            "text": item.text[:360],
                        }
                        for item in external_documents[:5]
                    ],
                },
                "signal_data_hub": data_hub_receipt,
            }
        )
        parsed = self.evidence_service.apply_confidence_policy(parsed, evidence_result)
        if canonical_bundle is not None:
            parsed.metadata["canonical_bundle"] = canonical_bundle.model_dump(mode="json")
        if source_health:
            parsed.metadata["source_health"] = [item.model_dump(mode="json") for item in source_health]
        if evidence_documents:
            parsed.metadata["input_evidence_document_count"] = len(evidence_documents)

        if source_type == SourceType.EARNINGS_CALL:
            snapshot = self.transcript_enhancer.evaluate(
                ticker=ticker,
                text_chunk=current_chunk,
                section_type=section_type,
                analysis=parsed,
                audio_features=parsed.metadata.get("audio_features") if isinstance(parsed.metadata, dict) else None,
            )
            parsed = self.transcript_enhancer.apply(parsed, snapshot)

        parsed = self.enrichment_pipeline.enrich(
            market_data=market_data,
            analysis=parsed,
            section_type=section_type,
            source_type=source_type,
            universe_profile=universe_profile,
        )

        approved_signal = (
            parsed.direction in {"BULLISH", "BEARISH"}
            and parsed.strategy not in {None, "SENTIMENT_ONLY"}
            and float(parsed.confidence) >= float(settings.confidence_threshold)
        )
        self.token_budgeter.record(
            TokenUsageEvent(
                route_profile=effective_profile,
                model=route_decision.model,
                prompt_tokens=int(usage.prompt_tokens or estimate_tokens(prompt)),
                output_tokens=int(usage.output_tokens or 0),
                total_tokens=int(usage.total_tokens or 0),
                estimated_cost_usd=float(usage.estimated_cost_usd or 0.0),
                cached=bool(usage.cached),
                coalesced=bool(usage.coalesced),
                approved_signal=approved_signal,
                budget_tokens=self.token_budgeter.prompt_budget(effective_profile),
            )
        )

        self.context_manager.add(
            ticker,
            ChunkRecord(
                sequence=chunk_sequence,
                text_chunk=current_chunk,
                section_type=section_type,
                source_type=source_type,
                raw_score=phase1.raw_score,
            ),
        )
        return parsed

    @staticmethod
    def _external_evidence_context(documents: list[object]) -> str:
        if not documents:
            return ""
        lines = ["EXTERNAL_EVIDENCE:"]
        for item in documents[:5]:
            lines.append(
                f"- {getattr(item, 'source_type', 'external')} | {getattr(item, 'title', '')} | "
                f"score={float(getattr(item, 'score', 0.0) or 0.0):.2f} | {str(getattr(item, 'text', ''))[:420]}"
            )
        return "\n".join(lines)


async def run_analysis(
    *,
    ticker: str,
    current_chunk: str,
    market_data: MarketData,
    section_type: SectionType,
    source_type: SourceType,
    chunk_sequence: int,
    request_priority: int,
    is_final: bool,
    route_profile: str | None = None,
    universe_profile: str | None = None,
    canonical_bundle: CanonicalEventBundle | None = None,
    source_health: list[CanonicalSourceHealth] | None = None,
    evidence_documents: list[EvidenceDocument] | None = None,
    request_metadata: dict[str, object] | None = None,
) -> GeminiAnalysisResult:
    service = AnalysisService()
    return await service.analyze(
        ticker=ticker,
        current_chunk=current_chunk,
        market_data=market_data,
        section_type=section_type,
        source_type=source_type,
        chunk_sequence=chunk_sequence,
        request_priority=request_priority,
        is_final=is_final,
        route_profile=route_profile,
        universe_profile=universe_profile,
        canonical_bundle=canonical_bundle,
        source_health=source_health,
        evidence_documents=evidence_documents,
        request_metadata=request_metadata,
    )
