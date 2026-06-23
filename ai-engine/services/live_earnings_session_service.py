"""Persistent orchestration for live earnings-call analysis sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import hashlib
import re
import time
from typing import Any
from uuid import uuid4

try:
    from config import Settings
    from core.investment_profiles import build_strategy_recommendation, resolve_investment_profile
    from models.evidence_models import ClaimDiffRequest, FactCheckRequest, FactCheckStatus, ImpactChainRequest, ImpactDirection, ImpactRelationship, OmissionAnalysisRequest, TradeExitPlanRequest, TradeExitPlanResponse
    from models.legacy_contract_models import LegacySignalMessage
    from models.live_session_models import EarningsScorecard, ExecutionMode, FactCheckProgress, FinalSignalAction, LiveEarningsSessionState, LiveExecutionPolicy, LiveFactCheckItem, LiveFinalSignal, LiveSessionStatus, LiveSessionStartRequest, LiveSessionSummary, LiveSpeakerProfile, LiveTranscriptChunkRequest, LiveTranscriptTimelineItem, RecommendedOrderTiming, RedisDeliveryState, utc_now
    from models.request_models import AnalyzeRequest, MarketData, SourceType
    from repositories.live_session_repository import LiveSessionRepository
    from services.company_intelligence_service import CompanyIntelligenceService
    from services.evidence_retrieval_service import EvidenceRetrievalService
    from services.redis_signal_publisher import RedisSignalPublisher
except ImportError:  # pragma: no cover
    from ..config import Settings
    from ..core.investment_profiles import build_strategy_recommendation, resolve_investment_profile
    from ..models.evidence_models import ClaimDiffRequest, FactCheckRequest, FactCheckStatus, ImpactChainRequest, ImpactDirection, ImpactRelationship, OmissionAnalysisRequest, TradeExitPlanRequest, TradeExitPlanResponse
    from ..models.legacy_contract_models import LegacySignalMessage
    from ..models.live_session_models import EarningsScorecard, ExecutionMode, FactCheckProgress, FinalSignalAction, LiveEarningsSessionState, LiveExecutionPolicy, LiveFactCheckItem, LiveFinalSignal, LiveSessionStatus, LiveSessionStartRequest, LiveSessionSummary, LiveSpeakerProfile, LiveTranscriptChunkRequest, LiveTranscriptTimelineItem, RecommendedOrderTiming, RedisDeliveryState, utc_now
    from ..models.request_models import AnalyzeRequest, MarketData, SourceType
    from ..repositories.live_session_repository import LiveSessionRepository
    from .company_intelligence_service import CompanyIntelligenceService
    from .evidence_retrieval_service import EvidenceRetrievalService
    from .redis_signal_publisher import RedisSignalPublisher

DispatchAnalysisFn = Callable[[AnalyzeRequest], Awaitable[dict[str, Any]]]
_GROWTH_POSITIVE = {"growth", "grew", "increase", "increased", "accelerate", "accelerated", "strong", "record", "demand", "bookings", "backlog"}
_GROWTH_NEGATIVE = {"decline", "declined", "decrease", "decreased", "slow", "slowed", "weak", "weaker", "soft", "lower"}
_PROFIT_POSITIVE = {"margin", "profit", "profitability", "income", "cash", "fcf", "leverage", "efficiency", "improved", "expanded"}
_PROFIT_NEGATIVE = {"pressure", "compressed", "compression", "loss", "cost", "dilution", "lower", "declined"}


def _clip(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _signed_score(analysis: dict[str, Any]) -> float:
    try:
        if analysis.get("raw_score") is not None:
            return _clamp(float(analysis["raw_score"]), -1.0, 1.0)
        magnitude = abs(float(analysis.get("magnitude") or 0.0))
    except (TypeError, ValueError):
        magnitude = 0.0
    direction = str(analysis.get("direction") or "").upper()
    if direction in {"BULLISH", "LONG", "BUY"}:
        return _clamp(magnitude, -1.0, 1.0)
    if direction in {"BEARISH", "SHORT", "SELL"}:
        return _clamp(-magnitude, -1.0, 1.0)
    return 0.0


def _analysis_from_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    analysis = envelope.get("analysis")
    return analysis if isinstance(analysis, dict) else {}


def _signal_brief_from_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    signal = envelope.get("signal_brief")
    if isinstance(signal, dict):
        return dict(signal)
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    signal = data.get("signal_brief")
    return dict(signal) if isinstance(signal, dict) else {}


def _engine_event_id(envelope: dict[str, Any]) -> str | None:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    event = data.get("event") if isinstance(data.get("event"), dict) else {}
    return str(event.get("event_id")) if event.get("event_id") else None


def _claim_id(ticker: str, claim: str) -> str:
    normalized = re.sub(r"\s+", " ", claim.strip().lower())
    return hashlib.sha1(f"{ticker}|{normalized}".encode("utf-8")).hexdigest()[:20]


class LiveEarningsSessionService:
    def __init__(self, *, repository: LiveSessionRepository, dispatcher: DispatchAnalysisFn, evidence_service: EvidenceRetrievalService, company_service: CompanyIntelligenceService, redis_publisher: RedisSignalPublisher | None, settings: Settings) -> None:
        self.repository = repository
        self.dispatcher = dispatcher
        self.evidence_service = evidence_service
        self.company_service = company_service
        self.redis_publisher = redis_publisher
        self.settings = settings
        self._locks: dict[str, asyncio.Lock] = {}

    def start(self, payload: LiveSessionStartRequest) -> LiveEarningsSessionState:
        ticker = payload.ticker.upper().strip()
        market_data = payload.market_data.model_copy(update={"ticker": payload.market_data.ticker or ticker})
        session_id = f"live_{ticker.lower()}_{uuid4().hex[:16]}"
        state = LiveEarningsSessionState(
            session_id=session_id, ticker=ticker, call_title=payload.call_title, fiscal_period=payload.fiscal_period,
            started_at=payload.call_started_at, updated_at=payload.call_started_at, expected_fact_count=payload.expected_fact_count,
            market_data=market_data, investment_profile=payload.investment_profile, execution_mode=payload.execution_mode,
            requested_quantity=payload.requested_quantity,
            related_tickers=list(dict.fromkeys(item.upper() for item in payload.related_tickers if item.strip() and item.upper() != ticker)),
            publish_final_signal=payload.publish_final_signal, fact_check_progress=FactCheckProgress(expected=payload.expected_fact_count),
            execution_policy=self._execution_policy(payload.execution_mode, action=FinalSignalAction.HOLD, execution_allowed=False),
            metadata={**payload.metadata, "storage_backend": self.repository.backend_name},
        )
        try:
            company = self.company_service.get(ticker)
            state.metadata["company_intelligence_backend"] = company.persistence_backend
            state.speakers = [self._speaker_from_metadata(item, company.executives) for item in company.speakers]
        except Exception as exc:
            state.warnings.append(f"company_intelligence_unavailable:{exc}")
        return self.repository.save(state)

    def get(self, session_id: str) -> LiveEarningsSessionState:
        state = self.repository.get(session_id)
        if state is None:
            raise KeyError(session_id)
        return state

    def list(self, *, ticker: str | None = None, status: LiveSessionStatus | None = None, limit: int = 50) -> list[LiveSessionSummary]:
        return self.repository.list(ticker=ticker, status=status, limit=limit)

    async def ingest_chunk(self, session_id: str, payload: LiveTranscriptChunkRequest) -> LiveEarningsSessionState:
        async with self._lock_for(session_id):
            state = self.get(session_id)
            if state.status != LiveSessionStatus.ACTIVE:
                raise ValueError("Completed live sessions cannot accept new transcript chunks.")
            sequence = payload.sequence if payload.sequence is not None else max((item.sequence for item in state.timeline), default=-1) + 1
            if any(item.sequence == sequence for item in state.timeline):
                raise ValueError(f"Transcript sequence {sequence} already exists in this session.")
            state.market_data = self._merge_market_data(state.market_data, payload.market_data)
            analyze_request = AnalyzeRequest(
                ticker=state.ticker, prompt=payload.text, market_data=state.market_data, section_type=payload.section_type,
                source_type=SourceType.EARNINGS_CALL, chunk_sequence=sequence, request_priority=payload.request_priority,
                is_final=payload.is_final, route_profile=payload.route_profile, investment_profile=state.investment_profile,
                evidence_documents=payload.evidence_documents,
                request_metadata={**payload.metadata, "live_session_id": state.session_id, "speaker_name": payload.speaker_name, "speaker_role": payload.speaker_role, "occurred_at": payload.occurred_at.isoformat()},
            )
            envelope = await self.dispatcher(analyze_request)
            analysis = _analysis_from_envelope(envelope)
            signal_brief = _signal_brief_from_envelope(envelope)
            score = _signed_score(analysis)
            new_claim_ids = self._process_claims(state=state, payload=payload, sequence=sequence)
            if payload.question:
                state.omission_events.append(self.evidence_service.analyze_omission(OmissionAnalysisRequest(ticker=state.ticker, question=payload.question, answer=payload.text, metadata={"session_id": state.session_id, "sequence": sequence})))
                state.omission_events = state.omission_events[-30:]
            self._update_speaker(state=state, payload=payload, claims=[item.claim for item in state.fact_checks if item.claim_id in new_claim_ids])
            state.timeline.append(LiveTranscriptTimelineItem(
                sequence=sequence, occurred_at=payload.occurred_at, speaker_name=payload.speaker_name, speaker_role=payload.speaker_role,
                text=payload.text, ai_score=round(score, 4), direction=str(analysis.get("direction") or "NEUTRAL"),
                confidence=_clamp(float(analysis.get("confidence") or 0.0)), action=str(signal_brief.get("action") or self._action_for_score(score).value),
                fact_check_ids=new_claim_ids, engine_event_id=_engine_event_id(envelope),
            ))
            state.timeline.sort(key=lambda item: (item.sequence, item.occurred_at))
            state.latest_signal_brief = signal_brief
            state.latest_engine_envelope = envelope
            state.updated_at = utc_now()
            state.fact_check_progress = self._fact_check_progress(state)
            state.scorecard = self._build_scorecard(state)
            self.repository.save(state)
            if payload.is_final:
                return await self._complete_state(state, envelope=envelope)
            return state

    async def finalize(self, session_id: str) -> LiveEarningsSessionState:
        async with self._lock_for(session_id):
            state = self.get(session_id)
            if state.status == LiveSessionStatus.COMPLETED:
                return state
            if not state.timeline:
                raise ValueError("At least one transcript chunk is required before finalization.")
            aggregate = "\n".join(item.text for item in state.timeline[-12:])
            sequence = max(item.sequence for item in state.timeline) + 1
            request = AnalyzeRequest(
                ticker=state.ticker, prompt=_clip(aggregate, 12000), market_data=state.market_data,
                source_type=SourceType.EARNINGS_CALL, chunk_sequence=sequence, request_priority=9,
                is_final=True, route_profile="review", needs_review=True, investment_profile=state.investment_profile,
                request_metadata={"live_session_id": state.session_id, "session_finalize": True},
            )
            envelope = await self.dispatcher(request)
            state.latest_engine_envelope = envelope
            state.latest_signal_brief = _signal_brief_from_envelope(envelope)
            return await self._complete_state(state, envelope=envelope)

    def _process_claims(self, *, state: LiveEarningsSessionState, payload: LiveTranscriptChunkRequest, sequence: int) -> list[str]:
        claims = self.evidence_service.extract_claims(payload.text)
        limit = max(1, int(getattr(self.settings, "live_session_max_fact_checks_per_chunk", 3)))
        existing_ids = {item.claim_id for item in state.fact_checks}
        new_claims: list[str] = []
        new_ids: list[str] = []
        for claim in claims:
            claim_id = _claim_id(state.ticker, claim)
            if claim_id in existing_ids:
                continue
            result = self.evidence_service.fact_check(FactCheckRequest(
                ticker=state.ticker, claim=claim, top_k=5, documents=payload.evidence_documents,
                metadata={"live_session_id": state.session_id, "sequence": sequence},
            ))
            state.fact_checks.append(LiveFactCheckItem(
                claim_id=claim_id, claim=claim, fact_check=result.fact_check, confidence=result.confidence,
                reason=result.reason, sequence=sequence, speaker_name=payload.speaker_name, evidence=result.evidence,
            ))
            existing_ids.add(claim_id)
            new_claims.append(claim)
            new_ids.append(claim_id)
            if len(new_claims) >= limit:
                break
        if new_claims:
            diff = self.evidence_service.claim_diff(ClaimDiffRequest(ticker=state.ticker, current_claims=new_claims, documents=payload.evidence_documents))
            known = {(item.current_claim, item.prior_claim) for item in state.claim_diffs}
            state.claim_diffs.extend(item for item in diff.items if (item.current_claim, item.prior_claim) not in known)
            state.claim_diffs = state.claim_diffs[-50:]
        state.fact_checks = state.fact_checks[-100:]
        return new_ids

    async def _complete_state(self, state: LiveEarningsSessionState, *, envelope: dict[str, Any]) -> LiveEarningsSessionState:
        state.latest_engine_envelope = envelope
        state.latest_signal_brief = _signal_brief_from_envelope(envelope)
        state.fact_check_progress = self._fact_check_progress(state)
        state.scorecard = self._build_scorecard(state)
        state.final_signal = self._build_final_signal(state, envelope)
        state.execution_policy = self._execution_policy(state.execution_mode, action=state.final_signal.action, execution_allowed=state.final_signal.execution_allowed)
        state.impact_chain = self._impact_chain(state)
        state.risk_plan = self._risk_plan(state)
        state.status = LiveSessionStatus.COMPLETED
        state.completed_at = utc_now()
        state.updated_at = state.completed_at
        self.repository.save(state)
        await self._publish_final_signal(state)
        return self.repository.save(state)

    def _build_final_signal(self, state: LiveEarningsSessionState, envelope: dict[str, Any]) -> LiveFinalSignal:
        scores = [item.ai_score for item in state.timeline]
        weights = list(range(1, len(scores) + 1))
        weighted_score = sum(score * weight for score, weight in zip(scores, weights)) / max(1, sum(weights))
        progress = self._fact_check_progress(state)
        processed = max(1, progress.processed)
        contradicted_ratio = progress.contradicted / processed
        unverified_ratio = progress.unverified / processed
        omission = sum(item.omission_score for item in state.omission_events) / max(1, len(state.omission_events))
        evidence_factor = max(0.35, 1.0 - contradicted_ratio * 0.5 - unverified_ratio * 0.15 - omission * 0.2)
        supported_ratio = progress.supported / processed
        review_score = _signed_score(_analysis_from_envelope(envelope))
        blended_score = weighted_score * 0.75 + review_score * 0.25
        signed_score = _clamp(blended_score * evidence_factor * (1.0 + supported_ratio * 0.1), -1.0, 1.0)
        profile = resolve_investment_profile(state.investment_profile)
        threshold = profile.action_threshold_abs if profile is not None else 0.12
        action = self._action_for_score(signed_score, threshold=threshold)
        latest_brief = _signal_brief_from_envelope(envelope)
        if str(latest_brief.get("action") or "").upper() == "AVOID":
            action = FinalSignalAction.HOLD
        confidence = _clamp(0.25 + abs(signed_score) * 0.35 + state.scorecard.evidence_quality / 100.0 * 0.2 + min(len(state.timeline), 5) / 5.0 * 0.12 + state.scorecard.management_confidence / 100.0 * 0.08 - contradicted_ratio * 0.18)
        analysis = _analysis_from_envelope(envelope)
        execution_allowed = bool(analysis.get("execution_allowed", True)) and action != FinalSignalAction.HOLD and confidence >= 0.55
        direction = "BULLISH" if action == FinalSignalAction.BUY else "BEARISH" if action == FinalSignalAction.SELL else "NEUTRAL"
        return LiveFinalSignal(
            signal_id=f"live-session:{state.session_id}", action=action, direction=direction, signed_score=round(signed_score, 4),
            confidence=round(confidence, 4), ai_score=state.scorecard.overall,
            rationale_ko=self._final_rationale(state, action, progress), execution_allowed=execution_allowed,
            strategy=str(analysis.get("strategy") or envelope.get("strategy") or "SENTIMENT_ONLY"),
            hold_days=max(1, int(analysis.get("hold_days") or 1)), risk_flags=list(analysis.get("risk_flags") or []),
            order_draft=self._order_draft(state, action, execution_allowed, envelope),
        )

    def _impact_chain(self, state: LiveEarningsSessionState):
        relationships: list[ImpactRelationship] = []
        try:
            company = self.company_service.get(state.ticker)
            relationships.extend(item.to_impact_relationship() for item in company.relationships)
        except Exception as exc:
            state.warnings.append(f"impact_graph_unavailable:{exc}")
        known = {item.ticker.upper() for item in relationships}
        for ticker in state.related_tickers:
            if ticker not in known:
                relationships.append(ImpactRelationship(ticker=ticker, relationship="user_supplied", strength=0.5, reason="사용자가 지정한 관련 종목"))
        direction = ImpactDirection.NEUTRAL
        if state.final_signal and state.final_signal.action == FinalSignalAction.BUY:
            direction = ImpactDirection.BULLISH
        elif state.final_signal and state.final_signal.action == FinalSignalAction.SELL:
            direction = ImpactDirection.BEARISH
        result = self.evidence_service.impact_chain(ImpactChainRequest(
            source_ticker=state.ticker, source_direction=direction,
            catalyst=_clip(" ".join(item.text for item in state.timeline[-6:]), 1800),
            confidence=state.final_signal.confidence if state.final_signal else 0.5,
            relationships=relationships, top_k=10, metadata={"live_session_id": state.session_id},
        ))
        return result.impacted

    def _risk_plan(self, state: LiveEarningsSessionState) -> TradeExitPlanResponse:
        signal = state.final_signal
        if signal is None or signal.action == FinalSignalAction.HOLD:
            return TradeExitPlanResponse(ticker=state.ticker, available=False, warnings=["HOLD 신호이므로 자동 손절·익절 가격을 활성화하지 않습니다."])
        return self.evidence_service.generate_trade_exit_plan(TradeExitPlanRequest(
            ticker=state.ticker, market_data=state.market_data.model_dump(mode="json"), strategy=signal.strategy,
            direction="LONG" if signal.action == FinalSignalAction.BUY else "SHORT", confidence=signal.confidence,
            hold_days=signal.hold_days, risk_flags=signal.risk_flags,
        ))

    async def _publish_final_signal(self, state: LiveEarningsSessionState) -> None:
        enabled = bool(getattr(self.settings, "live_session_redis_publish_enabled", True))
        if not enabled or not state.publish_final_signal or self.redis_publisher is None or state.final_signal is None:
            return
        signal = state.final_signal
        profile = resolve_investment_profile(state.investment_profile)
        recommendation = None
        if profile is not None:
            recommendation = build_strategy_recommendation(
                profile, strategy=signal.strategy, action=signal.action.value, confidence=signal.confidence,
                hold_days=signal.hold_days, risk_flags=signal.risk_flags,
            )
        text_chunk = state.timeline[-1].text if state.timeline else state.call_title
        legacy = LegacySignalMessage(
            ticker=state.ticker, raw_score=signal.signed_score, rationale=signal.rationale_ko, text_chunk=text_chunk,
            timestamp=int(time.time()), is_session_end=True, action=signal.action.value, confidence=signal.confidence,
            strategy=signal.strategy, hold_days=signal.hold_days, model_route="live_session_finalize",
            execution_allowed=signal.execution_allowed, blocked_reason_ko=None if signal.execution_allowed else signal.rationale_ko,
            signal_brief={**state.latest_signal_brief, "signal_id": signal.signal_id, "action": signal.action.value, "confidence": signal.confidence, "summary_ko": signal.rationale_ko, "live_session_id": state.session_id, "ai_score": signal.ai_score},
            engine_event_id=signal.signal_id,
            investment_profile=profile.code if profile else None,
            investment_profile_label_ko=profile.label_ko if profile else None,
            universe_profile=profile.universe_profile if profile else None,
            risk_style=profile.risk_style if profile else None,
            redis_output_profile=profile.redis_output_profile if profile else None,
            strategy_recommendation=recommendation,
        )
        enriched = {
            "schema_version": "2026-06-20.live-earnings-signal-v1",
            "signal_id": signal.signal_id,
            "legacy_signal": legacy.model_dump(mode="json", exclude_none=True),
            "live_session": {
                "session_id": state.session_id, "status": state.status.value,
                "scorecard": state.scorecard.model_dump(mode="json"),
                "fact_check_progress": state.fact_check_progress.model_dump(mode="json"),
                "execution_policy": state.execution_policy.model_dump(mode="json"),
                "risk_plan": state.risk_plan.model_dump(mode="json") if state.risk_plan else None,
            },
            "engine_envelope": state.latest_engine_envelope,
        }
        try:
            result = await self.redis_publisher.publish(legacy_signal=legacy, enriched_message=enriched)
            state.redis_delivery = RedisDeliveryState(
                attempted=True, legacy_published=result.legacy_published, enriched_published=result.enriched_published,
                profile_published=result.profile_published, profile_channel=result.profile_channel,
                retry_queued=result.retry_queued, error=result.error,
            )
        except Exception as exc:
            state.redis_delivery = RedisDeliveryState(attempted=True, error=str(exc))

    def _update_speaker(self, *, state: LiveEarningsSessionState, payload: LiveTranscriptChunkRequest, claims: list[str]) -> None:
        if not payload.speaker_name:
            return
        normalized = payload.speaker_name.strip().lower()
        profile = next((item for item in state.speakers if item.name.strip().lower() == normalized), None)
        if profile is None:
            profile = LiveSpeakerProfile(
                speaker_id=hashlib.sha1(f"{state.ticker}|{normalized}".encode("utf-8")).hexdigest()[:20],
                ticker=state.ticker, name=payload.speaker_name.strip(), role=payload.speaker_role or "unknown",
                is_executive=self._is_executive_role(payload.speaker_role),
            )
            try:
                company = self.company_service.get(state.ticker)
                source = next((item for item in company.speakers if item.name.strip().lower() == normalized), None)
                executive = next((item for item in company.executives if item.name.strip().lower() == normalized), None)
                if source is not None:
                    profile = self._speaker_from_metadata(source, company.executives)
                elif executive is not None:
                    profile.executive_profile = executive
                    profile.is_executive = True
                    profile.achievements = executive.achievements
                    profile.career_history = executive.career_history
                    profile.communication_traits = executive.communication_traits
                    profile.guidance_accuracy = self._guidance_accuracy(executive.metadata)
            except Exception:
                pass
            state.speakers.append(profile)
        profile.observed_chunks += 1
        if payload.speaker_role and profile.role == "unknown":
            profile.role = payload.speaker_role
        profile.observed_traits = list(dict.fromkeys(profile.observed_traits + self._observed_traits(payload.text)))[:12]
        profile.statement_history = list(dict.fromkeys(profile.statement_history + [_clip(item, 220) for item in claims]))[-12:]
        checks = [item for item in state.fact_checks if item.speaker_name and item.speaker_name.strip().lower() == normalized]
        if checks:
            profile.session_fact_accuracy = round(sum(item.fact_check == FactCheckStatus.SUPPORTED for item in checks) / len(checks), 4)

    @staticmethod
    def _speaker_from_metadata(speaker, executives) -> LiveSpeakerProfile:
        executive = next((item for item in executives if item.name.strip().lower() == speaker.name.strip().lower()), None)
        return LiveSpeakerProfile(
            speaker_id=speaker.speaker_id, ticker=speaker.ticker, name=speaker.name, role=speaker.role,
            is_executive=speaker.is_executive,
            guidance_accuracy=LiveEarningsSessionService._guidance_accuracy(executive.metadata if executive else speaker.metadata),
            achievements=list(executive.achievements if executive else []), career_history=list(executive.career_history if executive else []),
            communication_traits=list(executive.communication_traits if executive else []),
            source_profile=speaker, executive_profile=executive,
        )

    @staticmethod
    def _guidance_accuracy(metadata: dict[str, Any] | None) -> float | None:
        value = (metadata or {}).get("guidance_accuracy")
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return round(_clamp(parsed / 100.0 if parsed > 1.0 else parsed), 4)

    @staticmethod
    def _observed_traits(text: str) -> list[str]:
        lower = text.lower()
        traits: list[str] = []
        if re.search(r"\b\d+(?:\.\d+)?%|\$\s?\d", text):
            traits.append("수치 정밀")
        if any(term in lower for term in ("capex", "capital expenditure", "infrastructure investment")):
            traits.append("CapEx 강조")
        if any(term in lower for term in ("margin", "operating income", "profitability")):
            traits.append("마진 포커스")
        if any(term in lower for term in ("long term", "too early", "do not break out", "can't comment")):
            traits.append("회피 가능성")
        return traits or ["중립 톤"]

    @staticmethod
    def _is_executive_role(role: str | None) -> bool:
        normalized = str(role or "").lower()
        return any(term in normalized for term in ("chief", "ceo", "cfo", "president", "chair"))

    @staticmethod
    def _merge_market_data(current: MarketData, incoming: MarketData | None) -> MarketData:
        if incoming is None:
            return current
        payload = current.model_dump(mode="python")
        payload.update(incoming.model_dump(mode="python", exclude_unset=True))
        return MarketData.model_validate(payload)

    @staticmethod
    def _fact_check_progress(state: LiveEarningsSessionState) -> FactCheckProgress:
        supported = sum(item.fact_check == FactCheckStatus.SUPPORTED for item in state.fact_checks)
        contradicted = sum(item.fact_check == FactCheckStatus.CONTRADICTED for item in state.fact_checks)
        unverified = sum(item.fact_check == FactCheckStatus.UNVERIFIED for item in state.fact_checks)
        processed = len(state.fact_checks)
        return FactCheckProgress(processed=processed, expected=max(state.expected_fact_count, processed), supported=supported, contradicted=contradicted, unverified=unverified)

    @staticmethod
    def _build_scorecard(state: LiveEarningsSessionState) -> EarningsScorecard:
        transcript = " ".join(item.text for item in state.timeline).lower()
        tokens = set(re.findall(r"[a-z0-9-]+", transcript))
        scores = [item.ai_score for item in state.timeline]
        average_score = sum(scores) / max(1, len(scores))
        growth_delta = (len(tokens & _GROWTH_POSITIVE) - len(tokens & _GROWTH_NEGATIVE)) / max(1, len(tokens & (_GROWTH_POSITIVE | _GROWTH_NEGATIVE)))
        profit_delta = (len(tokens & _PROFIT_POSITIVE) - len(tokens & _PROFIT_NEGATIVE)) / max(1, len(tokens & (_PROFIT_POSITIVE | _PROFIT_NEGATIVE)))
        progress = LiveEarningsSessionService._fact_check_progress(state)
        processed = max(1, progress.processed)
        supported_ratio = progress.supported / processed
        contradicted_ratio = progress.contradicted / processed
        unverified_ratio = progress.unverified / processed
        avg_fact_confidence = sum(item.confidence for item in state.fact_checks) / max(1, len(state.fact_checks))
        evidence_coverage = sum(bool(item.evidence) for item in state.fact_checks) / max(1, len(state.fact_checks))
        average_analysis_confidence = sum(item.confidence for item in state.timeline) / max(1, len(state.timeline))
        average_evasion = sum(item.evasion_score for item in state.omission_events) / max(1, len(state.omission_events))
        average_omission = sum(item.omission_score for item in state.omission_events) / max(1, len(state.omission_events))
        high_diff_ratio = sum(item.risk_score >= 0.6 for item in state.claim_diffs) / max(1, len(state.claim_diffs))
        growth = _clamp(0.5 + average_score * 0.22 + growth_delta * 0.28) * 100
        profitability = _clamp(0.5 + average_score * 0.12 + profit_delta * 0.32) * 100
        risk_control = _clamp(0.78 - contradicted_ratio * 0.35 - average_evasion * 0.22 - average_omission * 0.18 - high_diff_ratio * 0.18) * 100
        management_confidence = _clamp(average_analysis_confidence * 0.72 + (1.0 - average_evasion) * 0.28) * 100
        guidance_reliability = _clamp(0.38 + supported_ratio * 0.48 - contradicted_ratio * 0.42 - unverified_ratio * 0.12) * 100
        evidence_quality = _clamp(avg_fact_confidence * 0.65 + evidence_coverage * 0.35) * 100 if state.fact_checks else 0.0
        overall = growth * 0.20 + profitability * 0.15 + risk_control * 0.15 + management_confidence * 0.15 + guidance_reliability * 0.20 + evidence_quality * 0.15
        return EarningsScorecard(
            growth=round(growth, 2), profitability=round(profitability, 2), risk_control=round(risk_control, 2),
            management_confidence=round(management_confidence, 2), guidance_reliability=round(guidance_reliability, 2),
            evidence_quality=round(evidence_quality, 2), overall=round(_clamp(overall, 0.0, 100.0), 2),
        )

    @staticmethod
    def _action_for_score(score: float, *, threshold: float = 0.12) -> FinalSignalAction:
        if score > threshold:
            return FinalSignalAction.BUY
        if score < -threshold:
            return FinalSignalAction.SELL
        return FinalSignalAction.HOLD

    @staticmethod
    def _execution_policy(mode: ExecutionMode, *, action: FinalSignalAction, execution_allowed: bool) -> LiveExecutionPolicy:
        eligible = execution_allowed and action != FinalSignalAction.HOLD
        return LiveExecutionPolicy(
            mode=mode, requires_user_confirmation=mode != ExecutionMode.AUTO_PILOT or not eligible,
            automation_eligible=mode == ExecutionMode.AUTO_PILOT and eligible,
            recommended_order_timing=RecommendedOrderTiming.AT_OPEN if eligible else RecommendedOrderTiming.WAIT_FOR_CONFIRMATION,
            rationale_ko=(
                "최종 신호는 저장되며 다음 정규장 시작 시 trading-terminal 정책으로 평가합니다. AI 엔진은 브로커를 호출하지 않습니다."
                if eligible else "근거가 혼재하거나 실행 게이트를 통과하지 못해 주문보다 추가 확인을 우선합니다."
            ),
        )

    @staticmethod
    def _final_rationale(state: LiveEarningsSessionState, action: FinalSignalAction, progress: FactCheckProgress) -> str:
        if action == FinalSignalAction.BUY:
            decision = "성장·수익성 발언과 근거 일치도가 우세해 분할 매수 후보로 분류했습니다."
        elif action == FinalSignalAction.SELL:
            decision = "약화 발언과 위험 신호가 우세해 매도 또는 비중 축소 후보로 분류했습니다."
        else:
            decision = "긍정 성장 신호와 CapEx·마진·근거 불확실성이 혼재해 관망으로 분류했습니다."
        return f"{decision} 팩트체크 {progress.processed}건 중 지지 {progress.supported}건, 불일치 {progress.contradicted}건, 검증불가 {progress.unverified}건이며 종합 AI 점수는 {state.scorecard.overall:.1f}점입니다."

    @staticmethod
    def _order_draft(state: LiveEarningsSessionState, action: FinalSignalAction, execution_allowed: bool, envelope: dict[str, Any]) -> dict[str, Any]:
        analysis = _analysis_from_envelope(envelope)
        metadata = analysis.get("metadata") if isinstance(analysis.get("metadata"), dict) else {}
        assistant = metadata.get("decision_assistant") if isinstance(metadata.get("decision_assistant"), dict) else {}
        existing = assistant.get("order_draft_preview") if isinstance(assistant.get("order_draft_preview"), dict) else {}
        price = float(state.market_data.current_price or 0.0)
        quantity = state.requested_quantity if action != FinalSignalAction.HOLD else None
        return {
            **existing, "advisory_only": True, "broker_execution": "not_called", "session_id": state.session_id,
            "ticker": state.ticker, "side": action.value,
            "order_type": "LIMIT_OR_MARKET_DRAFT" if execution_allowed else "NO_ORDER", "quantity": quantity,
            "reference_price": price if price > 0 else existing.get("reference_price"),
            "estimated_amount": round(price * quantity, 2) if price > 0 and quantity else None,
            "requires_terminal_confirmation": True,
        }

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock


__all__ = ["DispatchAnalysisFn", "LiveEarningsSessionService"]
