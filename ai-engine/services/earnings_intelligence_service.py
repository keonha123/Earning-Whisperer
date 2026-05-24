"""RAG-backed earnings-call intelligence service."""

from __future__ import annotations

from datetime import datetime
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
_RELATIONSHIPS = {
    "NVDA": [("AMD", "GPU peer"), ("TSM", "foundry supplier"), ("AVGO", "AI networking peer"), ("MU", "HBM memory supplier"), ("SMCI", "AI server supply-chain"), ("QQQ", "large-cap growth ETF")],
    "MSFT": [("GOOGL", "cloud/AI peer"), ("AMZN", "cloud peer"), ("META", "AI capex peer"), ("ORCL", "enterprise cloud peer"), ("QQQ", "large-cap growth ETF")],
    "META": [("GOOGL", "digital ads peer"), ("SNAP", "social ads peer"), ("NVDA", "AI infrastructure supplier"), ("QQQ", "large-cap growth ETF")],
    "TSLA": [("RIVN", "EV peer"), ("GM", "auto peer"), ("F", "auto peer"), ("ALB", "battery material exposure"), ("QQQ", "large-cap growth ETF")],
    "AAPL": [("QCOM", "component supplier"), ("AVGO", "wireless component supplier"), ("TSM", "foundry supplier"), ("QQQ", "large-cap growth ETF")],
}


class EarningsIntelligenceService:
    """Produces fact-check, contradiction, omission, impact-chain, and risk-plan outputs."""

    def __init__(self, retriever=external_retriever) -> None:
        self.retriever = retriever

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
        summary = _summary_ko(fact_checks=fact_checks, diffs=claim_diffs, evasion=omission_evasion, impact_chain=impact_chain)
        return EarningsIntelligenceResponse(
            ticker=ticker,
            evidence_count=len(retrieved),
            retrieved_evidence=[_to_payload(item) for item in retrieved],
            fact_checks=fact_checks,
            claim_diffs=claim_diffs,
            omission_evasion=omission_evasion,
            impact_chain=impact_chain,
            risk_plan=risk_plan,
            summary_ko=summary,
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
            rationale = "관련 근거는 있으나 방향성 검증은 부분적입니다."
        confidence = min(0.92, 0.45 + max(item.score for item in evidence[:3]) * 0.45)
        return ClaimFactCheck(claim=claim, verdict=verdict, confidence=round(confidence, 4), rationale_ko=rationale, evidence=[_to_payload(item) for item in evidence[:top_k]])

    def _claim_diff(self, *, ticker: str, claim: str, now: int) -> ClaimDiff:
        topic = _topic(claim)
        evidence = self.retriever.retrieve(query=claim, ticker=ticker, chunk_timestamp=now, preferred_sources=["ir", "filing", "press_release"], lookback_days=365, limit=3)
        prior = next((item for item in evidence if item.text.strip() != claim.strip()), None)
        if prior is None:
            return ClaimDiff(current_claim=claim, topic=topic, direction_change="unknown", contradiction_score=0.0, severity="low", rationale_ko="비교 가능한 과거 발언 근거가 부족합니다.", evidence=[])
        current_dir = _direction_score(claim)
        prior_dir = _direction_score(prior.text)
        contradiction = 0.0
        change = "unchanged"
        severity = "low"
        rationale = "과거 발언과 현재 발언의 방향성 변화가 제한적입니다."
        if current_dir and prior_dir and current_dir * prior_dir < 0:
            contradiction = min(1.0, 0.55 + prior.score * 0.35)
            change = "direction_flip"
            severity = "high" if contradiction >= 0.7 else "medium"
            rationale = "같은 주제에서 과거 발언과 현재 발언의 방향성이 반대로 바뀌었습니다."
        return ClaimDiff(current_claim=claim, prior_claim=prior.text[:320], topic=topic, direction_change=change, contradiction_score=round(contradiction, 4), severity=severity, rationale_ko=rationale, evidence=[_to_payload(prior)])

    def _impact_chain(
        self,
        *,
        ticker: str,
        event_text: str,
        explicit_related: list[str],
        retrieved: list[ExternalRetrievedDocument],
    ) -> list[ImpactNode]:
        direction = _direction_score(event_text)
        impact_direction = ImpactDirection.POSITIVE if direction > 0 else ImpactDirection.NEGATIVE if direction < 0 else ImpactDirection.NEUTRAL
        related = _related_tickers(ticker, explicit_related)
        evidence_payload = [_to_payload(item) for item in retrieved[:2]]
        nodes: list[ImpactNode] = []
        for rel, relationship in related[:10]:
            base = 0.42
            if any(term in relationship.lower() for term in ("supplier", "supply", "foundry", "memory")):
                base += 0.12
            if any(term in event_text.lower() for term in ("demand", "capex", "ai", "supply", "margin")):
                base += 0.14
            nodes.append(
                ImpactNode(
                    ticker=rel,
                    relationship=relationship,
                    direction=impact_direction,
                    impact_score=round(min(0.92, base), 4),
                    confidence=round(0.45 + min(0.35, len(evidence_payload) * 0.08), 4),
                    rationale_ko=f"{ticker} 이벤트가 {relationship} 관계를 통해 {rel}에 연쇄 영향을 줄 수 있습니다.",
                    evidence=evidence_payload,
                )
            )
        return nodes


def _to_external_document(item: ExternalEvidencePayload, *, default_ticker: str, fallback_timestamp: int) -> ExternalDocument:
    published_at = item.published_at
    if isinstance(published_at, datetime):
        ts = int(published_at.timestamp())
    elif isinstance(published_at, (int, float)):
        ts = int(published_at)
    else:
        ts = fallback_timestamp
    return ExternalDocument(
        doc_id=item.doc_id,
        ticker=(item.ticker or default_ticker).upper(),
        text=item.text,
        title=item.title,
        published_at=ts,
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
    pos = len(tokens & _POSITIVE)
    neg = len(tokens & _NEGATIVE)
    if pos > neg:
        return 1
    if neg > pos:
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
        return OmissionEvasionAnalysis(directness=1.0, evasion_score=0.0, omission_score=0.0, pivot_detected=False, missing_topics=[], rationale_ko="질문/답변 쌍이 없어 회피 분석을 생략했습니다.")
    q_topics = [_topic_word for _topic_word in _TOPIC_TERMS if _topic(question) == _topic_word]
    q_tokens = set(re.findall(r"[a-z0-9-]+", question.lower()))
    a_tokens = set(re.findall(r"[a-z0-9-]+", answer.lower()))
    required = {term for terms in _TOPIC_TERMS.values() for term in terms if term in q_tokens}
    missing = sorted(required - a_tokens)
    overlap = len((q_tokens - {"what", "when", "where", "how", "why", "can", "you"}) & a_tokens) / max(1, len(q_tokens))
    pivot = any(phrase in answer.lower() for phrase in _VAGUE_PHRASES)
    omission = min(1.0, len(missing) / max(1, len(required))) if required else 0.0
    evasion = min(1.0, (0.45 if pivot else 0.0) + max(0.0, 0.35 - overlap) + omission * 0.35)
    directness = max(0.0, 1.0 - evasion)
    rationale = "답변이 질문의 핵심 항목을 직접 다룹니다."
    if evasion >= 0.55:
        rationale = "답변이 질문의 핵심 주제를 일부 누락하거나 장기/일반론으로 전환했습니다."
    elif missing:
        rationale = "답변은 관련성이 있으나 질문의 일부 세부 항목을 누락했습니다."
    return OmissionEvasionAnalysis(directness=round(directness, 4), evasion_score=round(evasion, 4), omission_score=round(omission, 4), pivot_detected=pivot, missing_topics=missing or q_topics, rationale_ko=rationale)


def _risk_plan(*, direction_hint: str | None, confidence: float | None, market_data, contradiction: float, evasion: float) -> RiskPlan:
    price = float(getattr(market_data, "current_price", 0.0) or 0.0)
    direction = (direction_hint or "NEUTRAL").upper()
    if price <= 0 or direction not in {"BULLISH", "BEARISH"}:
        return RiskPlan(available=False, direction=direction, invalidation_text="가격 또는 방향성 신호가 부족해 자동 손절/익절 산출을 보류합니다.", sizing_note_ko="거래 보류", assumptions=[])
    atr_pct = float(getattr(market_data, "atr_pct_14", None) or 0.025)
    if atr_pct > 1.0:
        atr_pct /= 100.0
    atr_pct = max(0.012, min(0.12, atr_pct))
    confidence = 0.55 if confidence is None else max(0.0, min(1.0, confidence))
    risk_addon = contradiction * 0.018 + evasion * 0.012 + (1.0 - confidence) * 0.018
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
        invalidation_text="근거 모순, 회피 점수 상승, 또는 가격이 손절 기준을 이탈하면 진입 논리를 무효화합니다.",
        sizing_note_ko="모순/회피 리스크가 높으면 1/2 이하 포지션으로 축소합니다." if contradiction >= 0.5 or evasion >= 0.55 else "표준 리스크 한도 내 분할 진입을 우선합니다.",
        assumptions=["ATR 기반 일봉 근사", "실제 주문 전 스프레드/유동성 재확인 필요"],
    )


def _related_tickers(ticker: str, explicit: list[str]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    output: list[tuple[str, str]] = []
    for rel in explicit:
        normalized = rel.upper().strip()
        if normalized and normalized != ticker and normalized not in seen:
            seen.add(normalized)
            output.append((normalized, "user-supplied related ticker"))
    for rel, relationship in _RELATIONSHIPS.get(ticker, []):
        if rel not in seen:
            seen.add(rel)
            output.append((rel, relationship))
    if ticker not in {"SPY", "QQQ"} and "SPY" not in seen:
        output.append(("SPY", "broad market ETF"))
    return output


def _summary_ko(*, fact_checks: list[ClaimFactCheck], diffs: list[ClaimDiff], evasion: OmissionEvasionAnalysis, impact_chain: list[ImpactNode]) -> str:
    contradicted = sum(1 for item in fact_checks if item.verdict == FactCheckVerdict.CONTRADICTED)
    supported = sum(1 for item in fact_checks if item.verdict == FactCheckVerdict.SUPPORTED)
    high_diff = sum(1 for item in diffs if item.severity in {"medium", "high"})
    return f"근거 검증: 지지 {supported}건, 충돌 {contradicted}건. 과거 발언 변화 리스크 {high_diff}건, 회피 점수 {evasion.evasion_score:.2f}. 연쇄 영향 후보 {len(impact_chain)}개를 산출했습니다."


__all__ = ["EarningsIntelligenceService"]
