from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable

try:
    from core.trade_plan import build_trade_exit_plan
    from models.canonical_models import CanonicalEventBundle, CanonicalSourceHealth
    from models.evidence_models import (
        ClaimDiffItem,
        ClaimDiffRequest,
        ClaimDiffResponse,
        EvidenceBackend,
        EvidenceCitation,
        EvidenceDocument,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        EvidenceSourceType,
        FactCheckRequest,
        FactCheckResponse,
        FactCheckStatus,
        HistoricalClaim,
        ImpactChainItem,
        ImpactChainRequest,
        ImpactChainResponse,
        ImpactDirection,
        ImpactRelationship,
        OmissionAnalysisRequest,
        OmissionAnalysisResponse,
        TradeExitPlanRequest,
        TradeExitPlanResponse,
    )
    from models.request_models import MarketData, SourceType
    from models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
    from repositories.evidence_store_repository import EvidenceStoreRepository
except ImportError:  # pragma: no cover
    from ..core.trade_plan import build_trade_exit_plan
    from ..models.canonical_models import CanonicalEventBundle, CanonicalSourceHealth
    from ..models.evidence_models import (
        ClaimDiffItem,
        ClaimDiffRequest,
        ClaimDiffResponse,
        EvidenceBackend,
        EvidenceCitation,
        EvidenceDocument,
        EvidenceRetrievalRequest,
        EvidenceRetrievalResult,
        EvidenceSourceType,
        FactCheckRequest,
        FactCheckResponse,
        FactCheckStatus,
        HistoricalClaim,
        ImpactChainItem,
        ImpactChainRequest,
        ImpactChainResponse,
        ImpactDirection,
        ImpactRelationship,
        OmissionAnalysisRequest,
        OmissionAnalysisResponse,
        TradeExitPlanRequest,
        TradeExitPlanResponse,
    )
    from ..models.request_models import MarketData, SourceType
    from ..models.signal_models import GeminiAnalysisResult, StrategyDecision, StrategyName
    from ..repositories.evidence_store_repository import EvidenceStoreRepository


_POSITIVE = {
    "accelerate",
    "accelerated",
    "accelerating",
    "beat",
    "better",
    "expand",
    "expanded",
    "growth",
    "higher",
    "improve",
    "improved",
    "increase",
    "increased",
    "raise",
    "raised",
    "strong",
    "up",
}
_NEGATIVE = {
    "contract",
    "contracted",
    "cut",
    "decline",
    "declined",
    "decrease",
    "decreased",
    "defer",
    "deferred",
    "down",
    "disciplined",
    "lower",
    "miss",
    "pressure",
    "reduce",
    "reduced",
    "slow",
    "slowed",
    "weak",
    "weaker",
}
_TOPIC_KEYWORDS = {
    "guidance": {"guide", "guidance", "outlook", "forecast", "raise", "cut"},
    "margin": {"margin", "gross", "operating", "profitability", "cost"},
    "capex": {"capex", "capital", "infrastructure", "investment", "spend"},
    "demand": {"demand", "orders", "backlog", "customer", "bookings"},
    "revenue": {"revenue", "sales", "topline", "growth"},
    "supply": {"supply", "inventory", "capacity", "foundry", "memory"},
}

_DEFAULT_IMPACT_GRAPH: dict[str, list[ImpactRelationship]] = {
    "NVDA": [
        ImpactRelationship(ticker="TSMC", relationship="supplier/foundry", strength=0.82, beta=1.15, reason="GPU demand changes foundry volume expectations."),
        ImpactRelationship(ticker="AMD", relationship="peer/competitor", strength=0.68, beta=1.25, reason="AI accelerator demand reprices peers."),
        ImpactRelationship(ticker="AVGO", relationship="peer/custom silicon", strength=0.62, beta=1.12, reason="AI networking and ASIC read-through."),
        ImpactRelationship(ticker="SMCI", relationship="customer/server supply chain", strength=0.64, beta=1.4, reason="AI server demand read-through."),
        ImpactRelationship(ticker="MU", relationship="supplier/memory", strength=0.54, beta=1.35, reason="HBM and memory demand read-through."),
        ImpactRelationship(ticker="ARM", relationship="ecosystem/IP", strength=0.48, beta=1.2, reason="AI compute ecosystem sentiment."),
        ImpactRelationship(ticker="ASML", relationship="semicap supplier", strength=0.45, beta=1.05, reason="Leading-edge capacity demand."),
        ImpactRelationship(ticker="QQQ", relationship="ETF/mega-cap weight", strength=0.58, beta=1.0, etf_weight_pct=7.0, reason="Index-level AI mega-cap exposure."),
    ],
    "AMD": [
        ImpactRelationship(ticker="NVDA", relationship="peer/competitor", strength=0.70, beta=1.15),
        ImpactRelationship(ticker="TSMC", relationship="supplier/foundry", strength=0.62, beta=1.10),
        ImpactRelationship(ticker="MU", relationship="supplier/memory", strength=0.42, beta=1.25),
        ImpactRelationship(ticker="QQQ", relationship="ETF/semiconductor exposure", strength=0.36, beta=1.0),
    ],
    "TSMC": [
        ImpactRelationship(ticker="NVDA", relationship="customer", strength=0.76, beta=1.15),
        ImpactRelationship(ticker="AMD", relationship="customer", strength=0.58, beta=1.25),
        ImpactRelationship(ticker="ASML", relationship="supplier/semicap", strength=0.50, beta=1.05),
        ImpactRelationship(ticker="QQQ", relationship="ETF/supply chain exposure", strength=0.32, beta=1.0),
    ],
}


def _clip(text: str, limit: int = 360) -> str:
    normalized = " ".join(str(text or "").split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def _tokens(text: str) -> set[str]:
    tokens = set()
    for raw in re.findall(r"[a-z0-9][a-z0-9._%-]{1,}", (text or "").lower()):
        token = raw.strip("._%-")
        if token:
            tokens.add(token)
    return tokens


def _polarity(text: str) -> int:
    tokens = _tokens(text)
    positive = len(tokens & _POSITIVE)
    negative = len(tokens & _NEGATIVE)
    if positive > negative:
        return 1
    if negative > positive:
        return -1
    return 0


def _topic(text: str) -> str:
    tokens = _tokens(text)
    best_topic = "general"
    best_count = 0
    for topic, keywords in _TOPIC_KEYWORDS.items():
        count = len(tokens & keywords)
        if count > best_count:
            best_topic = topic
            best_count = count
    return best_topic


def _as_date_text(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


class EvidenceRetrievalService:
    def __init__(self, repository: EvidenceStoreRepository | None = None) -> None:
        self.repository = repository or EvidenceStoreRepository(backend=EvidenceBackend.LOCAL_SPARSE)

    def retrieve(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        return self.repository.search(request)

    def retrieve_for_analysis(
        self,
        *,
        ticker: str,
        current_chunk: str,
        source_type: SourceType,
        market_data: MarketData,
        canonical_bundle: CanonicalEventBundle | None,
        source_health: list[CanonicalSourceHealth] | None,
        request_metadata: dict[str, Any] | None,
        evidence_documents: list[EvidenceDocument] | None,
        top_k: int = 5,
    ) -> EvidenceRetrievalResult:
        documents: list[EvidenceDocument] = []
        documents.extend(evidence_documents or [])
        documents.extend(self._documents_from_canonical_bundle(ticker=ticker, bundle=canonical_bundle))
        documents.extend(self._documents_from_metadata(ticker=ticker, metadata=request_metadata or {}))
        query = self._analysis_query(ticker=ticker, current_chunk=current_chunk, source_type=source_type, market_data=market_data)
        result = self.retrieve(
            EvidenceRetrievalRequest(
                ticker=ticker,
                query=query,
                top_k=top_k,
                documents=documents,
                metadata={"source_health_count": len(source_health or [])},
            )
        )
        return result

    @staticmethod
    def apply_confidence_policy(analysis: GeminiAnalysisResult, retrieval: EvidenceRetrievalResult) -> GeminiAnalysisResult:
        analysis.metadata["evidence_retrieval"] = retrieval.model_dump(mode="json")
        if retrieval.confidence_adjustment < 0 and analysis.direction in {"BULLISH", "BEARISH"}:
            analysis.confidence = round(max(0.0, min(1.0, float(analysis.confidence) + retrieval.confidence_adjustment)), 4)
            if retrieval.missing_evidence and "missing_rag_evidence" not in analysis.risk_flags:
                analysis.risk_flags.append("missing_rag_evidence")
            elif retrieval.coverage_score < 0.35 and "weak_rag_evidence" not in analysis.risk_flags:
                analysis.risk_flags.append("weak_rag_evidence")
        elif retrieval.confidence_adjustment > 0:
            analysis.confidence = round(max(0.0, min(1.0, float(analysis.confidence) + retrieval.confidence_adjustment)), 4)
        return analysis

    def fact_check(self, request: FactCheckRequest) -> FactCheckResponse:
        retrieval = self.retrieve(
            EvidenceRetrievalRequest(
                ticker=request.ticker,
                query=request.claim,
                top_k=request.top_k,
                documents=request.documents,
                metadata=request.metadata,
            )
        )
        if not retrieval.evidence:
            return FactCheckResponse(
                ticker=request.ticker,
                claim=request.claim,
                fact_check=FactCheckStatus.UNVERIFIED,
                confidence=0.15,
                evidence=[],
                reason="No evidence matched the claim.",
            )
        claim_polarity = _polarity(request.claim)
        evidence_text = " ".join(item.snippet for item in retrieval.evidence[:3])
        evidence_polarity = _polarity(evidence_text)
        overlap = len(_tokens(request.claim) & _tokens(evidence_text)) / max(1, len(_tokens(request.claim)))
        top_confidence = retrieval.evidence[0].confidence_score
        if claim_polarity and evidence_polarity and claim_polarity != evidence_polarity and overlap >= 0.22:
            status = FactCheckStatus.CONTRADICTED
            confidence = min(0.95, max(0.45, top_confidence))
            reason = "Retrieved evidence has opposing directional language for the same topic."
        elif overlap >= 0.28 and top_confidence >= 0.38:
            status = FactCheckStatus.SUPPORTED
            confidence = min(0.95, max(0.40, top_confidence))
            reason = "Retrieved evidence overlaps with the claim and does not contradict its direction."
        else:
            status = FactCheckStatus.UNVERIFIED
            confidence = min(0.70, max(0.25, top_confidence * 0.72))
            reason = "Evidence was related but not specific enough to verify the claim."
        return FactCheckResponse(
            ticker=request.ticker,
            claim=request.claim,
            fact_check=status,
            confidence=round(confidence, 4),
            evidence=retrieval.evidence,
            reason=reason,
        )

    def claim_diff(self, request: ClaimDiffRequest) -> ClaimDiffResponse:
        current_claims = request.current_claims or self.extract_claims(request.current_text or "")
        historical = list(request.historical_claims)
        historical.extend(self._historical_claims_from_documents(request.documents))
        items: list[ClaimDiffItem] = []
        for current in current_claims:
            topic = _topic(current)
            prior = self._best_prior_claim(current, topic, historical)
            if prior is None:
                change_type = "NEW_CLAIM"
                risk_score = 0.25
                prior_claim = None
                evidence: list[EvidenceCitation] = []
            else:
                current_polarity = _polarity(current)
                prior_polarity = _polarity(prior.claim)
                if current_polarity and prior_polarity and current_polarity != prior_polarity:
                    change_type = "DIRECTIONAL_SHIFT"
                    risk_score = 0.72
                elif current_polarity == prior_polarity and current_polarity != 0:
                    change_type = "REAFFIRMATION"
                    risk_score = 0.18
                else:
                    change_type = "NUANCE_CHANGE"
                    risk_score = 0.42
                prior_claim = prior.claim
                evidence = self.retrieve(
                    EvidenceRetrievalRequest(
                        ticker=request.ticker,
                        query=current,
                        top_k=2,
                        documents=[self._document_from_historical_claim(prior)],
                    )
                ).evidence
            items.append(
                ClaimDiffItem(
                    topic=topic,
                    prior_claim=prior_claim,
                    current_claim=current,
                    change_type=change_type,
                    risk_score=round(risk_score, 4),
                    evidence=evidence,
                )
            )
        max_risk = max((item.risk_score for item in items), default=0.0)
        return ClaimDiffResponse(ticker=request.ticker, items=items, max_risk_score=round(max_risk, 4))

    def analyze_omission(self, request: OmissionAnalysisRequest) -> OmissionAnalysisResponse:
        question_topic = _topic(request.question)
        required_slots = request.required_slots or self._required_slots_for_question(request.question, question_topic)
        answered_slots = [slot for slot in required_slots if self._slot_answered(slot, request.answer)]
        omitted_slots = [slot for slot in required_slots if slot not in answered_slots]
        omission_score = len(omitted_slots) / max(1, len(required_slots))
        vague_terms = {"long-term", "later", "appropriate", "dynamic", "various", "many", "several", "we will see"}
        vague_hits = sum(1 for term in vague_terms if term in request.answer.lower())
        evasion_score = min(1.0, omission_score * 0.78 + min(0.22, vague_hits * 0.06))
        return OmissionAnalysisResponse(
            ticker=request.ticker,
            question_topic=question_topic,
            required_slots=required_slots,
            answered_slots=answered_slots,
            omitted_slots=omitted_slots,
            omission_score=round(omission_score, 4),
            evasion_score=round(evasion_score, 4),
        )

    def impact_chain(self, request: ImpactChainRequest) -> ImpactChainResponse:
        source = request.source_ticker.upper()
        relationships = request.relationships or _DEFAULT_IMPACT_GRAPH.get(source, [])
        direction = request.source_direction
        if direction == ImpactDirection.NEUTRAL and request.catalyst:
            direction = self._direction_from_polarity(_polarity(request.catalyst))
        impacted: list[ImpactChainItem] = []
        for relationship in relationships:
            score = self._impact_score(relationship=relationship, confidence=request.confidence)
            impact_direction = self._relationship_direction(direction, relationship.relationship)
            evidence = []
            if request.catalyst:
                evidence = self.retrieve(
                    EvidenceRetrievalRequest(
                        ticker=source,
                        query=f"{source} {relationship.ticker} {relationship.relationship} {request.catalyst}",
                        top_k=2,
                        documents=[
                            EvidenceDocument(
                                ticker=source,
                                source_type=EvidenceSourceType.SUPPLY_CHAIN,
                                source="impact_graph",
                                title=f"{source} to {relationship.ticker} relationship",
                                content=relationship.reason or relationship.relationship,
                                reliability_score=0.68,
                            )
                        ],
                    )
                ).evidence
            impacted.append(
                ImpactChainItem(
                    ticker=relationship.ticker.upper(),
                    relationship=relationship.relationship,
                    impact_direction=impact_direction,
                    impact_score=score,
                    reason_ko=relationship.reason or f"{source} event has {relationship.relationship} read-through.",
                    evidence=evidence,
                    metadata={
                        "relationship_strength": relationship.strength,
                        "beta": relationship.beta,
                        "etf_weight_pct": relationship.etf_weight_pct,
                    },
                )
            )
        impacted.sort(key=lambda item: item.impact_score, reverse=True)
        return ImpactChainResponse(source_ticker=source, impacted=impacted[: request.top_k])

    def generate_trade_exit_plan(self, request: TradeExitPlanRequest) -> TradeExitPlanResponse:
        market_data = MarketData.model_validate(request.market_data)
        try:
            strategy = StrategyName(request.strategy)
        except ValueError:
            strategy = StrategyName.SENTIMENT_ONLY
        analysis = GeminiAnalysisResult(
            direction="BEARISH" if request.direction.upper() == "SHORT" else "BULLISH",
            magnitude=request.confidence,
            confidence=request.confidence,
            rationale="standalone trade-exit generation",
            catalyst_type="MANUAL",
        )
        decision = StrategyDecision(
            strategy=strategy,
            score=request.confidence,
            hold_days=request.hold_days,
            rationale="standalone exit plan",
            risk_flags=list(request.risk_flags),
            metadata={"hold_tuning": {"mfe_mae_profile": dict(request.mfe_mae_profile or {})}},
        )
        plan = build_trade_exit_plan(market_data, decision, analysis)
        return TradeExitPlanResponse(ticker=request.ticker.upper(), **plan)

    @staticmethod
    def extract_claims(text: str) -> list[str]:
        candidates = [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text or "") if item.strip()]
        claims = []
        claim_verbs = _POSITIVE | _NEGATIVE | {"will", "expect", "expects", "remain", "remains", "drive", "drives"}
        for candidate in candidates:
            tokens = _tokens(candidate)
            if len(tokens) >= 4 and (tokens & claim_verbs or _topic(candidate) != "general"):
                claims.append(_clip(candidate, 260))
        return claims[:8]

    @staticmethod
    def _analysis_query(*, ticker: str, current_chunk: str, source_type: SourceType, market_data: MarketData) -> str:
        market_terms = []
        if market_data.gap_pct:
            market_terms.append(f"gap {market_data.gap_pct}")
        if market_data.surprise_pct:
            market_terms.append(f"surprise {market_data.surprise_pct}")
        if market_data.sector_code:
            market_terms.append(str(market_data.sector_code))
        return _clip(f"{ticker} {source_type.value} {current_chunk} {' '.join(market_terms)}", 720)

    @staticmethod
    def _documents_from_canonical_bundle(*, ticker: str, bundle: CanonicalEventBundle | None) -> list[EvidenceDocument]:
        if bundle is None:
            return []
        event_date = bundle.earnings_event.event_time if bundle.earnings_event else None
        company_ticker = ticker or (bundle.company.ticker if bundle.company else None)
        documents: list[EvidenceDocument] = []
        if bundle.transcript:
            transcript_parts = [
                bundle.transcript.prepared_summary or "",
                bundle.transcript.qa_summary or "",
                " ".join(bundle.transcript.key_quotes[:5]),
            ]
            content = " ".join(part for part in transcript_parts if part)
            if content:
                documents.append(
                    EvidenceDocument(
                        ticker=company_ticker,
                        source_type=EvidenceSourceType.EARNINGS_CALL,
                        source="canonical_bundle.transcript",
                        title="Canonical earnings-call transcript summary",
                        published_at=event_date,
                        content=content,
                        reliability_score=0.82,
                    )
                )
        if bundle.guidance and bundle.guidance.summary:
            guidance_metrics = []
            for key in ("revenue_growth_pct", "margin_delta_pct", "capex_delta_pct"):
                value = getattr(bundle.guidance, key, None)
                if value is not None:
                    guidance_metrics.append(f"{key}={value}")
            documents.append(
                EvidenceDocument(
                    ticker=company_ticker,
                    source_type=EvidenceSourceType.HISTORICAL_GUIDANCE,
                    source="canonical_bundle.guidance",
                    title=f"Guidance {bundle.guidance.direction or 'update'}",
                    published_at=event_date,
                    content=" ".join([bundle.guidance.summary, " ".join(guidance_metrics)]),
                    reliability_score=0.84,
                )
            )
        return documents

    def _documents_from_metadata(self, *, ticker: str, metadata: dict[str, Any]) -> list[EvidenceDocument]:
        documents: list[EvidenceDocument] = []
        raw_documents = metadata.get("evidence_documents") or metadata.get("documents") or []
        if isinstance(raw_documents, list):
            for item in raw_documents:
                if isinstance(item, EvidenceDocument):
                    documents.append(item)
                elif isinstance(item, dict):
                    documents.append(EvidenceDocument.model_validate(item))
        raw_claims = metadata.get("historical_claims") or []
        if isinstance(raw_claims, list):
            for item in raw_claims:
                if isinstance(item, HistoricalClaim):
                    documents.append(self._document_from_historical_claim(item))
                elif isinstance(item, dict):
                    documents.append(self._document_from_historical_claim(HistoricalClaim.model_validate(item)))
                elif isinstance(item, str):
                    documents.append(
                        EvidenceDocument(
                            ticker=ticker,
                            source_type=EvidenceSourceType.HISTORICAL_GUIDANCE,
                            source="request_metadata.historical_claims",
                            title="Historical claim",
                            content=item,
                            reliability_score=0.66,
                        )
                    )
        return documents

    @staticmethod
    def _document_from_historical_claim(claim: HistoricalClaim) -> EvidenceDocument:
        return EvidenceDocument(
            ticker=claim.ticker,
            source_type=claim.source_type,
            source=claim.source,
            title=f"Historical claim: {claim.topic}",
            published_at=claim.stated_at,
            content=claim.claim,
            reliability_score=claim.confidence,
            metadata={"claim_id": claim.claim_id, "topic": claim.topic},
        )

    @staticmethod
    def _historical_claims_from_documents(documents: Iterable[EvidenceDocument]) -> list[HistoricalClaim]:
        claims: list[HistoricalClaim] = []
        for document in documents:
            if document.source_type != EvidenceSourceType.HISTORICAL_GUIDANCE:
                continue
            claims.append(
                HistoricalClaim(
                    claim_id=document.document_id,
                    ticker=document.ticker,
                    topic=str(document.metadata.get("topic") or _topic(document.content)),
                    claim=document.content,
                    stated_at=document.published_at,
                    source=document.source,
                    source_type=document.source_type,
                    confidence=document.reliability_score,
                )
            )
        return claims

    @staticmethod
    def _best_prior_claim(current: str, topic: str, historical: list[HistoricalClaim]) -> HistoricalClaim | None:
        current_tokens = _tokens(current)
        candidates = [item for item in historical if item.topic == topic] or historical
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: len(current_tokens & _tokens(item.claim)) / max(1, len(current_tokens | _tokens(item.claim))),
        )

    @staticmethod
    def _required_slots_for_question(question: str, topic: str) -> list[str]:
        question_tokens = _tokens(question)
        if topic == "margin" or {"margin", "cost", "pressure"} & question_tokens:
            return ["margin impact", "timeframe", "cost driver"]
        if topic == "capex":
            return ["spend level", "timeframe", "return driver"]
        if topic == "guidance":
            return ["revenue outlook", "margin impact", "timeframe"]
        if topic == "demand":
            return ["demand driver", "customer or geography", "timeframe"]
        return ["metric", "direction", "timeframe"]

    @staticmethod
    def _slot_answered(slot: str, answer: str) -> bool:
        answer_tokens = _tokens(answer)
        slot_tokens = _tokens(slot)
        slot_aliases = {
            "margin impact": {"margin", "bps", "basis", "gross", "operating"},
            "timeframe": {"quarter", "year", "month", "fy", "q1", "q2", "q3", "q4", "2026", "2027"},
            "cost driver": {"cost", "mix", "freight", "labor", "component", "pricing"},
            "spend level": {"capex", "spend", "investment", "dollar", "budget"},
            "return driver": {"roi", "return", "capacity", "growth", "throughput"},
            "revenue outlook": {"revenue", "sales", "outlook", "guide", "growth"},
            "demand driver": {"demand", "orders", "customer", "backlog", "bookings"},
            "customer or geography": {"customer", "enterprise", "cloud", "china", "us", "europe", "region"},
            "metric": {"revenue", "margin", "eps", "cash", "capex", "volume"},
            "direction": _POSITIVE | _NEGATIVE,
        }
        required = slot_aliases.get(slot, slot_tokens)
        return bool(answer_tokens & required)

    @staticmethod
    def _impact_score(*, relationship: ImpactRelationship, confidence: float) -> float:
        beta_component = min(abs(float(relationship.beta or 1.0)) / 2.0, 1.0) * 0.10
        etf_component = min(float(relationship.etf_weight_pct or 0.0) / 10.0, 1.0) * 0.10
        score = relationship.strength * 0.55 + confidence * 0.25 + beta_component + etf_component
        return round(max(0.0, min(1.0, score)), 4)

    @staticmethod
    def _direction_from_polarity(polarity: int) -> ImpactDirection:
        if polarity > 0:
            return ImpactDirection.BULLISH
        if polarity < 0:
            return ImpactDirection.BEARISH
        return ImpactDirection.NEUTRAL

    @staticmethod
    def _relationship_direction(source_direction: ImpactDirection, relationship: str) -> ImpactDirection:
        if source_direction in {ImpactDirection.NEUTRAL, ImpactDirection.MIXED}:
            return source_direction
        lowered = relationship.lower()
        if "competitor" in lowered and "peer" not in lowered:
            return ImpactDirection.MIXED
        return source_direction


__all__ = ["EvidenceRetrievalService"]
