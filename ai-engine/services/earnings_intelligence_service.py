"""RAG-backed earnings-call fact checking and market-impact intelligence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import time

try:
    from core.external_retriever import ExternalDocument, ExternalRetrievedDocument, external_retriever
    from models.earnings_intelligence_models import (
        ClaimDiff,
        ClaimFactCheck,
        EarningsIntelligenceRequest,
        EarningsIntelligenceResponse,
        ExternalEvidencePayload,
        FactCheckVerdict,
        ImpactDirection,
        ImpactNode,
        OmissionEvasionAnalysis,
        RetrievedEvidencePayload,
        RiskPlan,
    )
    from repositories.company_intelligence_repository import CompanyIntelligenceRepository
except ImportError:  # pragma: no cover
    from ..core.external_retriever import ExternalDocument, ExternalRetrievedDocument, external_retriever
    from ..models.earnings_intelligence_models import (
        ClaimDiff,
        ClaimFactCheck,
        EarningsIntelligenceRequest,
        EarningsIntelligenceResponse,
        ExternalEvidencePayload,
        FactCheckVerdict,
        ImpactDirection,
        ImpactNode,
        OmissionEvasionAnalysis,
        RetrievedEvidencePayload,
        RiskPlan,
    )
    from ..repositories.company_intelligence_repository import CompanyIntelligenceRepository


_POSITIVE = {
    "raise", "raised", "raising", "higher", "strong", "stronger", "improve", "improved",
    "expansion", "accelerate", "growth", "beat", "above", "healthy", "robust",
}
_NEGATIVE = {
    "lower", "lowered", "cut", "weak", "weaker", "decline", "declined", "pressure",
    "compression", "slowdown", "below", "miss", "risk", "headwind", "soft",
}
_TOPIC_TERMS = {
    "guidance": {"guidance", "outlook", "forecast", "full-year", "fy"},
    "margin": {"margin", "gross", "operating", "profitability"},
    "demand": {"demand", "orders", "bookings", "backlog", "customer"},
    "capex": {"capex", "investment", "capacity", "spending"},
    "liquidity": {"cash", "debt", "liquidity", "dilution", "balance"},
}
_VAGUE_PHRASES = {
    "as we said", "long term", "not going to comment", "can't comment", "too early",
    "we are focused", "more to come", "we do not break out", "hard to say",
}


class EarningsIntelligenceService:
    """Produces evidence-grounded claim, omission, impact, and risk-plan outputs."""

    def __init__(self, retriever=external_retriever, company_repository: CompanyIntelligenceRepository | None = None) -> None:
        self.retriever = retriever
        self.company_repository = company_repository or CompanyIntelligenceRepository(
            store_path=Path(__file__).resolve().parents[1] / "data" / "company_intelligence_seed.json"
        )

    async def analyze(self, payload: EarningsIntelligenceRequest) -> EarningsIntelligenceResponse:
        ticker = payload.ticker.upper()
        now = int(time.time())
        evidence_docs = [_to_external_document(item, default_ticker=ticker, fallback_timestamp=now) for item in payload.external_documents]
        if evidence_docs:
            self.retriever.upsert_documents(evidence_docs)
        retrieved = self.retriever.retrieve(
            query=f"{ticker} {payload.event_text}",
            ticker=ticker,
            chunk_timestamp=now,
            preferred_sources=[],
            lookback_days=30,
            limit=payload.top_k,
        )
        claims = _extract_claims(payload.event_text)
        fact_checks = [self._fact_check_claim(ticker=ticker, claim=claim, now=now, top_k=payload.top_k) for claim in claims[:5]]
        claim_diffs = [self._claim_diff(ticker=ticker, claim=claim, now=now) for claim in claims[:4]]
        omission_evasion = _omission_evasion(payload.question, payload.answer)
        impact_chain = self._impact_chain(
            ticker=ticker,
            event_text=payload.event_text,
            explicit_related=payload.related_tickers,
            retrieved=retrieved,
        )
        risk_plan = _risk_plan(
            direction_hint=payload.direction_hint,
            confidence=payload.confidence_hint,
            market_data=payload.market_data,
            contradiction=max((diff.contradiction_score for diff in claim_diffs), default=0.0),
            evasion=omission_evasion.evasion_score,
        )
        warnings: list[str] = []
        if not retrieved:
            warnings.append("RAG evidence is empty; output is heuristic and should not be treated as verified.")
        if any(item.verdict == FactCheckVerdict.CONTRADICTED for item in fact_checks):
            warnings.append("At least one claim conflicts with retrieved evidence.")
        return EarningsIntelligenceResponse(
            ticker=ticker,
            evidence_count=len(retrieved),
            retrieved_evidence=[_to_payload(item) for item in retrieved],
            fact_checks=fact_checks,
            claim_diffs=claim_diffs,
            omission_evasion=omission_evasion,
            impact_chain=impact_chain,
            company_intelligence={
                "relationships": [item.model_dump(mode="json") for item in self.company_repository.get_relationships(ticker)],
                "executives": [item.model_dump(mode="json") for item in self.company_repository.get_executives(ticker)],
                "speakers": [item.model_dump(mode="json") for item in self.company_repository.get_speakers(ticker)],
                "persistence_backend": self.company_repository.backend_name,
            },
            risk_plan=risk_plan,
            summary_ko=_summary_ko(fact_checks=fact_checks, diffs=claim_diffs, evasion=omission_evasion, impact_chain=impact_chain),
            warnings=warnings,
        )

    def _fact_check_claim(self, *, ticker: str, claim: str, now: int, top_k: int) -> ClaimFactCheck:
        evidence = self.retriever.retrieve(query=claim, ticker=ticker, chunk_timestamp=now, preferred_sources=[], lookback_days=365, limit=top_k)
        if not evidence:
            return ClaimFactCheck(
                claim=claim,
                verdict=FactCheckVerdict.INSUFFICIENT_EVIDENCE,
                confidence=0.25,
                rationale_ko="검색된 근거가 없어 사실 검증을 보류합니다.",
                evidence=[],
            )
        claim_dir = _direction_score(claim)
        evidence_dir = _direction_score(" ".join(item.text for item in evidence[:3]))
        if claim_dir and evidence_dir and claim_dir * evidence_dir < 0:
            verdict = FactCheckVerdict.CONTRADICTED
            rationale = "현재 발언의 방향성이 검색된 근거와 반대입니다."
        elif claim_dir and evidence_dir and claim_dir * evidence_dir > 0:
            verdict = FactCheckVerdict.SUPPORTED
            rationale = "현재 발언의 핵심 방향성이 검색된 근거와 일치합니다."
        else:
            verdict = FactCheckVerdict.PARTIAL
            rationale = "관련 근거는 있으나 발언 전체를 직접 검증하기에는 부족합니다."
        confidence = min(0.92, 0.45 + max(item.score for item in evidence[:3]) * 0.45)
        return ClaimFactCheck(
            claim=claim,
            verdict=verdict,
            confidence=round(confidence, 4),
            rationale_ko=rationale,
            evidence=[_to_payload(item) for item in evidence[:top_k]],
        )

    def _claim_diff(self, *, ticker: str, claim: str, now: int) -> ClaimDiff:
        topic = _topic(claim)
        evidence = self.retriever.retrieve(
            query=claim,
            ticker=ticker,
            chunk_timestamp=now,
            preferred_sources=["earnings_call", "filing", "earnings_release", "historical_guidance", "ir", "press_release"],
            lookback_days=365,
            limit=5,
        )
        prior = next((item for item in evidence if item.text.strip() != claim.strip()), None)
        if prior is None:
            return ClaimDiff(
                current_claim=claim,
                topic=topic,
                direction_change="unknown",
                contradiction_score=0.0,
                severity="low",
                rationale_ko="비교 가능한 과거 발언 근거가 부족합니다.",
                evidence=[],
            )
        current_dir = _direction_score(claim)
        prior_dir = _direction_score(prior.text)
        contradiction = 0.0
        change = "unchanged"
        severity = "low"
        rationale = "과거 발언과 현재 발언 사이에 뚜렷한 방향 변화가 확인되지 않았습니다."
        if current_dir and prior_dir and current_dir * prior_dir < 0:
            contradiction = min(1.0, 0.55 + prior.score * 0.35)
            change = "direction_flip"
            severity = "high" if contradiction >= 0.7 else "medium"
            rationale = "같은 주제에서 과거 발언과 현재 발언의 방향성이 반대로 바뀌었습니다."
        return ClaimDiff(
            current_claim=claim,
            prior_claim=prior.text[:320],
            topic=topic,
            direction_change=change,
            contradiction_score=round(contradiction, 4),
            severity=severity,
            rationale_ko=rationale,
            evidence=[_to_payload(prior)],
        )

    def _impact_chain(
        self,
        *,
        ticker: str,
        event_text: str,
        explicit_related: list[str],
        retrieved: list[ExternalRetrievedDocument],
    ) -> list[ImpactNode]:
        direction_score = _direction_score(event_text)
        base_direction = ImpactDirection.POSITIVE if direction_score > 0 else ImpactDirection.NEGATIVE if direction_score < 0 else ImpactDirection.NEUTRAL
        stored = self.company_repository.get_relationships(ticker)
        relationships: list[tuple[str, str, float, float, str]] = []
        seen: set[str] = set()
        for related_ticker in explicit_related:
            normalized = related_ticker.upper().strip()
            if normalized and normalized != ticker and normalized not in seen:
                seen.add(normalized)
                relationships.append((normalized, "user-supplied related ticker", 0.5, 1.0, "사용자가 지정한 관련 종목입니다."))
        for item in stored:
            normalized = item.target_ticker.upper()
            if normalized not in seen:
                seen.add(normalized)
                relationships.append((normalized, item.relationship, item.strength, item.direction_multiplier, item.reason_ko))
        if ticker not in {"SPY", "QQQ"} and "SPY" not in seen:
            relationships.append(("SPY", "broad market ETF", 0.25, 1.0, "시장 전체 위험 선호에 미치는 간접 영향입니다."))
        evidence_payload = [_to_payload(item) for item in retrieved[:2]]
        nodes: list[ImpactNode] = []
        for rel, relationship, strength, direction_multiplier, reason in relationships[:20]:
            direction = base_direction
            if direction_multiplier < 0:
                direction = ImpactDirection.NEGATIVE if base_direction == ImpactDirection.POSITIVE else ImpactDirection.POSITIVE if base_direction == ImpactDirection.NEGATIVE else base_direction
            catalyst_bonus = 0.12 if any(term in event_text.lower() for term in ("demand", "capex", "ai", "supply", "margin")) else 0.0
            score = min(0.95, 0.28 + strength * 0.55 + catalyst_bonus)
            confidence = min(0.92, 0.42 + len(evidence_payload) * 0.08 + strength * 0.2)
            nodes.append(
                ImpactNode(
                    ticker=rel,
                    relationship=relationship,
                    direction=direction,
                    impact_score=round(score, 4),
                    confidence=round(confidence, 4),
                    rationale_ko=reason or f"{ticker} 이벤트가 {relationship} 관계를 통해 {rel}에 연쇄 영향을 줄 수 있습니다.",
                    evidence=evidence_payload,
                )
            )
        nodes.sort(key=lambda item: item.impact_score, reverse=True)
        return nodes[:10]


def _to_external_document(item: ExternalEvidencePayload, *, default_ticker: str, fallback_timestamp: int) -> ExternalDocument:
    published_at = item.published_at
    if isinstance(published_at, datetime):
        timestamp = int(published_at.timestamp())
    elif isinstance(published_at, (int, float)):
        timestamp = int(published_at)
    else:
        timestamp = fallback_timestamp
    return ExternalDocument(
        doc_id=item.doc_id,
        ticker=(item.ticker or default_ticker).upper(),
        text=item.text,
        title=item.title,
        published_at=timestamp,
        source_type=item.source_type,
        url=item.url,
        form_type=item.form_type,
        importance=item.importance,
        metadata=dict(item.metadata),
    )


def _to_payload(item: ExternalRetrievedDocument) -> RetrievedEvidencePayload:
    return RetrievedEvidencePayload(
        doc_id=item.doc_id,
        title=item.title,
        text=item.text,
        score=item.score,
        published_at=item.published_at,
        source_type=item.source_type,
        url=item.url,
        form_type=item.form_type,
        metadata=dict(item.metadata),
    )


def _extract_claims(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if len(part.strip().split()) >= 5]
    material = [item for item in sentences if _topic(item) != "general" or _direction_score(item) != 0]
    return material[:6] or sentences[:3] or [text.strip()]


def _direction_score(text: str) -> int:
    tokens = set(re.findall(r"[a-z-]+", (text or "").lower()))
    positive = len(tokens & _POSITIVE)
    negative = len(tokens & _NEGATIVE)
    if positive > negative:
        return 1
    if negative > positive:
        return -1
    return 0


def _topic(text: str) -> str:
    tokens = set(re.findall(r"[a-z0-9-]+", (text or "").lower()))
    for topic, terms in _TOPIC_TERMS.items():
        if tokens & terms:
            return topic
    return "general"


def _omission_evasion(question: str | None, answer: str | None) -> OmissionEvasionAnalysis:
    if not question or not answer:
        return OmissionEvasionAnalysis(
            directness=1.0,
            evasion_score=0.0,
            omission_score=0.0,
            pivot_detected=False,
            missing_topics=[],
            rationale_ko="질문과 답변 쌍이 없어 회피 분석을 생략했습니다.",
        )
    q_topics = [topic for topic in _TOPIC_TERMS if _topic(question) == topic]
    q_tokens = set(re.findall(r"[a-z0-9-]+", question.lower()))
    a_tokens = set(re.findall(r"[a-z0-9-]+", answer.lower()))
    required = {term for terms in _TOPIC_TERMS.values() for term in terms if term in q_tokens}
    missing = sorted(required - a_tokens)
    overlap = len((q_tokens - {"what", "when", "where", "how", "why", "can", "you"}) & a_tokens) / max(1, len(q_tokens))
    pivot = any(phrase in answer.lower() for phrase in _VAGUE_PHRASES)
    omission = min(1.0, len(missing) / max(1, len(required))) if required else 0.0
    evasion = min(1.0, (0.45 if pivot else 0.0) + max(0.0, 0.35 - overlap) + omission * 0.35)
    directness = max(0.0, 1.0 - evasion)
    rationale = "답변이 질문의 핵심 항목을 직접 다루고 있습니다."
    if evasion >= 0.55:
        rationale = "답변이 질문의 핵심 주제를 일부 회피하거나 장기·일반론으로 전환했습니다."
    elif missing:
        rationale = "답변은 관련성이 있지만 질문의 일부 핵심 항목이 누락됐습니다."
    return OmissionEvasionAnalysis(
        directness=round(directness, 4),
        evasion_score=round(evasion, 4),
        omission_score=round(omission, 4),
        pivot_detected=pivot,
        missing_topics=missing or q_topics,
        rationale_ko=rationale,
    )


def _risk_plan(*, direction_hint: str | None, confidence: float | None, market_data, contradiction: float, evasion: float) -> RiskPlan:
    price = float(getattr(market_data, "current_price", 0.0) or 0.0)
    direction = (direction_hint or "NEUTRAL").upper()
    if price <= 0 or direction not in {"BULLISH", "BEARISH"}:
        return RiskPlan(
            available=False,
            direction=direction,
            invalidation_text="가격 또는 방향성 정보가 부족해 자동 손절·익절 산출을 보류합니다.",
            sizing_note_ko="거래 보류",
            assumptions=[],
        )
    atr_pct = float(getattr(market_data, "atr_pct_14", None) or 0.025)
    if atr_pct > 1.0:
        atr_pct /= 100.0
    atr_pct = max(0.012, min(0.12, atr_pct))
    confidence_value = 0.55 if confidence is None else max(0.0, min(1.0, confidence))
    risk_addon = contradiction * 0.018 + evasion * 0.012 + (1.0 - confidence_value) * 0.018
    stop_pct = max(0.02, min(0.09, atr_pct * 1.25 + risk_addon))
    tp1_pct = max(stop_pct * 1.25, atr_pct * 1.9)
    tp2_pct = max(stop_pct * 2.0, atr_pct * 3.0)
    sign = 1 if direction == "BULLISH" else -1
    stop = price * (1 - sign * stop_pct)
    tp1 = price * (1 + sign * tp1_pct)
    tp2 = price * (1 + sign * tp2_pct)
    return RiskPlan(
        available=True,
        direction="LONG" if direction == "BULLISH" else "SHORT",
        reference_price=round(price, 4),
        stop_loss=round(stop, 4),
        take_profit_1=round(tp1, 4),
        take_profit_2=round(tp2, 4),
        stop_pct=round(stop_pct * 100, 3),
        take_profit_1_pct=round(tp1_pct * 100, 3),
        take_profit_2_pct=round(tp2_pct * 100, 3),
        risk_reward_1=round(tp1_pct / stop_pct, 3),
        risk_reward_2=round(tp2_pct / stop_pct, 3),
        trailing_stop_pct=round(max(stop_pct * 0.75, atr_pct) * 100, 3),
        time_stop_days=3,
        invalidation_text="근거 모순이나 회피 점수가 상승하거나 가격이 손절 기준을 이탈하면 진입 논리를 무효화합니다.",
        sizing_note_ko="모순·회피 위험이 높아 절반 이하 포지션으로 축소합니다." if contradiction >= 0.5 or evasion >= 0.55 else "총 위험 한도 안에서 분할 진입을 우선합니다.",
        assumptions=["ATR 기반 변동성 근사", "실제 주문 전 스프레드와 유동성 재확인 필요"],
    )


def _summary_ko(*, fact_checks: list[ClaimFactCheck], diffs: list[ClaimDiff], evasion: OmissionEvasionAnalysis, impact_chain: list[ImpactNode]) -> str:
    contradicted = sum(1 for item in fact_checks if item.verdict == FactCheckVerdict.CONTRADICTED)
    supported = sum(1 for item in fact_checks if item.verdict == FactCheckVerdict.SUPPORTED)
    high_diff = sum(1 for item in diffs if item.severity in {"medium", "high"})
    return f"근거 검증 결과 지지 {supported}건, 충돌 {contradicted}건, 과거 발언 변화 위험 {high_diff}건, 회피 점수 {evasion.evasion_score:.2f}, 연쇄 영향 후보 {len(impact_chain)}개입니다."


__all__ = ["EarningsIntelligenceService"]
