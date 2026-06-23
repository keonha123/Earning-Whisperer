from __future__ import annotations

from fastapi.testclient import TestClient

import main
from config import Settings
from models.evidence_models import (
    ClaimDiffItem,
    ClaimDiffResponse,
    EvidenceBackend,
    EvidenceCitation,
    EvidenceSourceType,
    FactCheckResponse,
    FactCheckStatus,
    ImpactChainItem,
    ImpactChainResponse,
    ImpactDirection,
    OmissionAnalysisResponse,
    TradeExitPlanResponse,
)
from models.intelligence_models import CompanyIntelligenceResponse, ExecutiveProfile, SpeakerMetadata
from models.legacy_contract_models import LegacyPublishResult
from models.live_session_models import FinalSignalAction, LiveSessionStartRequest, LiveSessionStatus, LiveTranscriptChunkRequest
from repositories.live_session_repository import LiveSessionRepository
from services.live_earnings_session_service import LiveEarningsSessionService


class FakeEvidenceService:
    @staticmethod
    def extract_claims(text: str) -> list[str]:
        return [text]

    @staticmethod
    def fact_check(request) -> FactCheckResponse:
        contradicted = "capex" in request.claim.lower()
        status = FactCheckStatus.CONTRADICTED if contradicted else FactCheckStatus.SUPPORTED
        citation = EvidenceCitation(
            document_id="orcl-evidence-1",
            ticker="ORCL",
            source_type=EvidenceSourceType.EARNINGS_RELEASE,
            source="Q4 release",
            title="Oracle earnings release",
            published_at="2026-06-18",
            snippet="OCI growth was strong while infrastructure investment increased.",
            relevance_score=0.9,
            reliability_score=0.95,
            confidence_score=0.92,
        )
        return FactCheckResponse(
            ticker="ORCL",
            claim=request.claim,
            fact_check=status,
            confidence=0.9 if not contradicted else 0.82,
            evidence=[citation],
            reason="Matched earnings-release evidence.",
        )

    @staticmethod
    def claim_diff(request) -> ClaimDiffResponse:
        items = [
            ClaimDiffItem(
                topic="capex" if "capex" in claim.lower() else "growth",
                prior_claim="Investment will remain disciplined.",
                current_claim=claim,
                change_type="DIRECTIONAL_SHIFT" if "capex" in claim.lower() else "REAFFIRMATION",
                risk_score=0.72 if "capex" in claim.lower() else 0.18,
            )
            for claim in request.current_claims
        ]
        return ClaimDiffResponse(ticker="ORCL", items=items, max_risk_score=max(item.risk_score for item in items))

    @staticmethod
    def analyze_omission(request) -> OmissionAnalysisResponse:
        return OmissionAnalysisResponse(
            ticker="ORCL",
            question_topic="margin",
            required_slots=["margin impact", "timeframe"],
            answered_slots=[],
            omitted_slots=["margin impact", "timeframe"],
            omission_score=1.0,
            evasion_score=0.78,
        )

    @staticmethod
    def impact_chain(request) -> ImpactChainResponse:
        return ImpactChainResponse(
            source_ticker="ORCL",
            impacted=[
                ImpactChainItem(
                    ticker="MSFT",
                    relationship="cloud peer",
                    impact_direction=request.source_direction,
                    impact_score=0.62,
                    reason_ko="클라우드 성장률의 동종업계 연쇄효과",
                )
            ],
        )

    @staticmethod
    def generate_trade_exit_plan(request) -> TradeExitPlanResponse:
        return TradeExitPlanResponse(ticker="ORCL", available=True, time_stop_days=3)


class FakeCompanyService:
    @staticmethod
    def get(ticker: str) -> CompanyIntelligenceResponse:
        executive = ExecutiveProfile(
            executive_id="hilary",
            ticker=ticker,
            name="Hilary Maxson",
            current_role="Chief Financial Officer",
            achievements=["Scaled cloud infrastructure finance"],
            communication_traits=["numeric", "margin-focused"],
            metadata={"guidance_accuracy": 0.89},
        )
        speaker = SpeakerMetadata(
            speaker_id="hilary",
            ticker=ticker,
            name="Hilary Maxson",
            role="Chief Financial Officer",
            is_executive=True,
        )
        return CompanyIntelligenceResponse(ticker=ticker, executives=[executive], speakers=[speaker])


class FakePublisher:
    def __init__(self) -> None:
        self.calls = 0
        self.signals = []

    async def publish(self, *, legacy_signal, enriched_message=None):
        self.calls += 1
        self.signals.append((legacy_signal, enriched_message))
        return LegacyPublishResult(legacy_published=True, enriched_published=True)


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, payload):
        self.calls += 1
        text = payload.current_chunk.lower()
        if payload.request_metadata.get("session_finalize"):
            direction, magnitude, confidence, action = "NEUTRAL", 0.05, 0.74, "HOLD"
        elif "capex" in text:
            direction, magnitude, confidence, action = "BEARISH", 0.25, 0.76, "SELL"
        else:
            direction, magnitude, confidence, action = "BULLISH", 0.50, 0.84, "BUY"
        return {
            "status": "ok",
            "strategy": "PEAD",
            "analysis": {
                "direction": direction,
                "magnitude": magnitude,
                "confidence": confidence,
                "rationale": "deterministic test analysis",
                "strategy": "PEAD",
                "hold_days": 3,
                "execution_allowed": True,
                "risk_flags": ["management_contradiction_risk"] if "capex" in text else [],
                "metadata": {"decision_assistant": {"order_draft_preview": {"advisory_only": True, "broker_execution": "not_called"}}},
            },
            "signal_brief": {"action": action, "confidence": confidence, "summary_ko": "test"},
            "data": {"event": {"event_id": f"evt-{self.calls}"}},
        }


def build_service(tmp_path):
    settings = Settings(
        live_session_store_path=str(tmp_path / "live_sessions"),
        live_session_redis_publish_enabled=True,
        live_session_max_fact_checks_per_chunk=2,
        evidence_sync_enabled=False,
    )
    publisher = FakePublisher()
    dispatcher = FakeDispatcher()
    repository = LiveSessionRepository(store_path=tmp_path / "live_sessions", retention_hours=24, max_sessions=20)
    service = LiveEarningsSessionService(
        repository=repository,
        dispatcher=dispatcher,
        evidence_service=FakeEvidenceService(),
        company_service=FakeCompanyService(),
        redis_publisher=publisher,
        settings=settings,
    )
    return service, publisher, dispatcher, repository


def test_execution_mode_uses_terminal_contract_and_accepts_legacy_aliases() -> None:
    one_click = LiveSessionStartRequest(ticker="ORCL", execution_mode="ONE_CLICK")
    auto = LiveSessionStartRequest(ticker="ORCL", execution_mode="AUTO")

    assert one_click.execution_mode.value == "SEMI_AUTO"
    assert auto.execution_mode.value == "AUTO_PILOT"
    assert one_click.model_dump(mode="json")["execution_mode"] == "SEMI_AUTO"


def test_orcl_live_session_mixed_signal_finalizes_hold_and_recovers(tmp_path) -> None:
    service, publisher, dispatcher, repository = build_service(tmp_path)
    state = service.start(LiveSessionStartRequest(
        ticker="ORCL",
        call_title="Oracle live earnings call",
        fiscal_period="FY2026 Q4",
        expected_fact_count=2,
        market_data={"ticker": "ORCL", "current_price": 210.0, "atr_pct_14": 0.035},
        investment_profile="NASDAQ100_CONSERVATIVE",
        execution_mode="ONE_CLICK",
        requested_quantity=10,
        related_tickers=["MSFT"],
    ))

    import asyncio

    state = asyncio.run(service.ingest_chunk(state.session_id, LiveTranscriptChunkRequest(
        sequence=0,
        speaker_name="Hilary Maxson",
        speaker_role="Chief Financial Officer",
        text="OCI revenue growth increased 52% and demand remained strong.",
    )))
    state = asyncio.run(service.ingest_chunk(state.session_id, LiveTranscriptChunkRequest(
        sequence=1,
        speaker_name="Hilary Maxson",
        speaker_role="Chief Financial Officer",
        question="What is the margin impact and timeframe?",
        text="CapEx will increase sharply for infrastructure investment while margins face pressure.",
    )))
    finalized = asyncio.run(service.finalize(state.session_id))
    repeated = asyncio.run(service.finalize(state.session_id))

    assert finalized.status == LiveSessionStatus.COMPLETED
    assert finalized.final_signal is not None
    assert finalized.final_signal.action == FinalSignalAction.HOLD
    assert finalized.final_signal.signal_id == f"live-session:{state.session_id}"
    assert finalized.final_signal.order_draft["broker_execution"] == "not_called"
    assert finalized.execution_policy.automation_eligible is False
    assert finalized.execution_mode.value == "SEMI_AUTO"
    assert finalized.execution_policy.mode.value == "SEMI_AUTO"
    assert finalized.fact_check_progress.processed == 2
    assert finalized.fact_check_progress.supported == 1
    assert finalized.fact_check_progress.contradicted == 1
    assert finalized.omission_events[0].evasion_score == 0.78
    assert finalized.speakers[0].guidance_accuracy == 0.89
    assert finalized.speakers[0].session_fact_accuracy == 0.5
    assert "수치 정밀" in finalized.speakers[0].observed_traits
    assert finalized.impact_chain[0].ticker == "MSFT"
    assert finalized.risk_plan is not None and finalized.risk_plan.available is False
    assert publisher.calls == 1
    assert repeated.redis_delivery.legacy_published is True
    assert dispatcher.calls == 3

    recovered = LiveSessionRepository(store_path=repository.store_path).get(state.session_id)
    assert recovered is not None
    assert recovered.status == LiveSessionStatus.COMPLETED
    assert recovered.final_signal is not None
    assert recovered.final_signal.signal_id == finalized.final_signal.signal_id


def test_live_session_api_start_ingest_query_and_finalize(tmp_path) -> None:
    service, publisher, _, _ = build_service(tmp_path)
    app = main.create_app()
    app.state.live_session_service = service
    client = TestClient(app)

    created = client.post("/v1/engine/live-sessions", json={"ticker": "ORCL", "expected_fact_count": 1, "publish_final_signal": True})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    chunk = client.post(
        f"/v1/engine/live-sessions/{session_id}/chunks",
        json={"sequence": 0, "speaker_name": "Hilary Maxson", "speaker_role": "Chief Financial Officer", "text": "Cloud revenue growth increased 30%."},
    )
    assert chunk.status_code == 200
    assert chunk.json()["fact_check_progress"]["processed"] == 1

    listed = client.get("/v1/engine/live-sessions", params={"ticker": "ORCL"})
    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["session_id"] == session_id

    finalized = client.post(f"/v1/engine/live-sessions/{session_id}/finalize")
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "COMPLETED"
    assert finalized.json()["final_signal"]["order_draft"]["broker_execution"] == "not_called"
    assert publisher.calls == 1
