from __future__ import annotations

import asyncio

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from api.routers import ALL_ROUTERS
    from config import Settings, get_settings
    from core.analysis_service import AnalysisService, run_analysis
    from core.external_retriever import ExternalRetrieverFacade
    from db.postgres_executor import PsycopgExecutor
    from models.evidence_models import EvidenceBackend
    from models.request_models import AnalyzeRequest
    from models.storage_models import PersistEnvelopeResponse
    from repositories.company_intelligence_repository import CompanyIntelligenceRepository
    from repositories.event_store_repository import EventStoreRepository
    from repositories.evidence_store_repository import EvidenceStoreRepository
    from repositories.live_session_repository import LiveSessionRepository
    from services import CalibrationService, CompanyIntelligenceService, ControlPlaneService, EarningsIntelligenceService, EquityResearchReportService, EvidenceIngestionScheduler, EvidenceIngestionService, EvidenceRetrievalService, LiveEarningsSessionService, RegressionService
    from services.redis_signal_publisher import RedisSignalPublisher
    from services.runtime_dispatch_service import dispatch_analysis
except ImportError:  # pragma: no cover
    from .api.routers import ALL_ROUTERS
    from .config import Settings, get_settings
    from .core.analysis_service import AnalysisService, run_analysis
    from .core.external_retriever import ExternalRetrieverFacade
    from .db.postgres_executor import PsycopgExecutor
    from .models.evidence_models import EvidenceBackend
    from .models.request_models import AnalyzeRequest
    from .models.storage_models import PersistEnvelopeResponse
    from .repositories.company_intelligence_repository import CompanyIntelligenceRepository
    from .repositories.event_store_repository import EventStoreRepository
    from .repositories.evidence_store_repository import EvidenceStoreRepository
    from .repositories.live_session_repository import LiveSessionRepository
    from .services import CalibrationService, CompanyIntelligenceService, ControlPlaneService, EarningsIntelligenceService, EquityResearchReportService, EvidenceIngestionScheduler, EvidenceIngestionService, EvidenceRetrievalService, LiveEarningsSessionService, RegressionService
    from .services.redis_signal_publisher import RedisSignalPublisher
    from .services.runtime_dispatch_service import dispatch_analysis


class HealthResponse(BaseModel):
    status: str
    models: dict[str, str]


def risk_score_from_sentiment(sentiment_score: float) -> float:
    return min(1.0, abs(sentiment_score) * 1.5)


async def _dispatch_analysis(
    payload: AnalyzeRequest,
    settings: Settings,
    fastapi_app: FastAPI | None = None,
) -> dict[str, Any]:
    current_app = fastapi_app if fastapi_app is not None else globals().get("app")
    analysis_runner = run_analysis
    if current_app is not None:
        analysis_service = getattr(current_app.state, "analysis_service", None)
        if analysis_service is not None and hasattr(analysis_service, "analyze"):
            analysis_runner = analysis_service.analyze
    return await dispatch_analysis(
        payload=payload,
        settings=settings,
        analysis_runner=analysis_runner,
        control_service=_get_control_service(current_app),
    )


def _schema_path_from_settings(settings: Settings) -> Path:
    configured = Path(settings.db_schema_path)
    if configured.is_absolute():
        return configured
    return Path(__file__).resolve().parent / configured


def _build_repository(settings: Settings) -> EventStoreRepository:
    executor = PsycopgExecutor(
        dsn=settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
        failure_cooldown_seconds=settings.database_failure_cooldown_seconds,
    )
    return EventStoreRepository(executor=executor, schema_path=_schema_path_from_settings(settings))


def _resolve_ai_engine_path(configured: str) -> Path:
    path = Path(configured)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def _build_evidence_repository(settings: Settings) -> EvidenceStoreRepository:
    executor = None
    if settings.evidence_postgres_enabled:
        executor = PsycopgExecutor(
            dsn=settings.database_url,
            connect_timeout_seconds=settings.database_connect_timeout_seconds,
            failure_cooldown_seconds=settings.database_failure_cooldown_seconds,
        )
    backend = EvidenceBackend.QDRANT if settings.vector_store_backend.lower() == "qdrant" else EvidenceBackend.LOCAL_SPARSE
    return EvidenceStoreRepository(
        backend=backend,
        executor=executor,
        schema_path=_resolve_ai_engine_path(settings.evidence_schema_path),
    )


def _build_company_repository(settings: Settings, evidence_repository: EvidenceStoreRepository) -> CompanyIntelligenceRepository:
    return CompanyIntelligenceRepository(
        store_path=_resolve_ai_engine_path(settings.company_intelligence_store_path),
        executor=evidence_repository.executor,
        schema_path=_resolve_ai_engine_path(settings.evidence_schema_path),
        seed_path=Path(__file__).resolve().parent / "data" / "company_intelligence_seed.json",
    )

def _get_control_service(fastapi_app: FastAPI | None) -> ControlPlaneService | None:
    if fastapi_app is None or not hasattr(fastapi_app.state, "event_store_repository"):
        return None
    return ControlPlaneService(fastapi_app.state.event_store_repository)


def _get_calibration_service(fastapi_app: FastAPI) -> CalibrationService:
    return CalibrationService(fastapi_app.state.event_store_repository)


def _get_regression_service(fastapi_app: FastAPI) -> RegressionService:
    return RegressionService(fastapi_app.state.event_store_repository)


def _persist_or_raise(repository: EventStoreRepository, envelope: dict[str, Any]) -> PersistEnvelopeResponse:
    try:
        result = repository.save_event_envelope(envelope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        raise HTTPException(status_code=500, detail=f"Failed to persist engine envelope: {exc}") from exc
    return PersistEnvelopeResponse(
        status="ok",
        persisted=result.persisted,
        event_id=result.event_id,
        run_id=result.run_id,
        row_counts=result.row_counts,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="EarningWhisperer AI Engine", version=settings.app_version)

    app.config = {
        "GEMINI_FAST_MODEL": settings.gemini_primary_model,
        "GEMINI_PRO_MODEL": settings.gemini_review_model,
        "GEMINI_PRIMARY_MODEL": settings.gemini_primary_model,
        "GEMINI_REVIEW_MODEL": settings.gemini_review_model,
        "ENABLE_REVIEW_PASS": settings.enable_review_pass,
    }

    app.state.settings = settings
    app.state.evidence_repository = _build_evidence_repository(settings)
    app.state.company_intelligence_repository = _build_company_repository(settings, app.state.evidence_repository)
    app.state.evidence_service = EvidenceRetrievalService(
        repository=app.state.evidence_repository,
        company_repository=app.state.company_intelligence_repository,
    )
    app.state.external_retriever = ExternalRetrieverFacade()
    app.state.analysis_service = AnalysisService(
        settings=settings,
        evidence_service=app.state.evidence_service,
        external_retriever_service=app.state.external_retriever,
    )
    app.state.company_intelligence_service = CompanyIntelligenceService(app.state.company_intelligence_repository)
    app.state.evidence_ingestion_service = EvidenceIngestionService(
        settings=settings,
        evidence_service=app.state.evidence_service,
        external_retriever=app.state.analysis_service.external_retriever,
        company_service=app.state.company_intelligence_service,
    )
    app.state.evidence_ingestion_scheduler = EvidenceIngestionScheduler(
        service=app.state.evidence_ingestion_service,
        settings=settings,
    )
    app.state.event_store_repository = _build_repository(settings)
    app.state.redis_signal_publisher = RedisSignalPublisher(settings=settings)
    app.state.equity_report_service = EquityResearchReportService(
        settings=settings,
        token_budgeter=app.state.analysis_service.token_budgeter,
    )
    app.state.earnings_intelligence_service = EarningsIntelligenceService(
        retriever=app.state.analysis_service.external_retriever,
        company_repository=app.state.company_intelligence_repository,
    )
    app.state.control_plane_service = _get_control_service(app)
    app.state.calibration_service = _get_calibration_service(app)
    app.state.regression_service = _get_regression_service(app)
    app.state.dispatch_analysis = lambda payload, _app=app: _dispatch_analysis(payload, settings, _app)
    app.state.live_session_repository = LiveSessionRepository(
        store_path=_resolve_ai_engine_path(settings.live_session_store_path),
        executor=app.state.evidence_repository.executor,
        retention_hours=settings.live_session_retention_hours,
        max_sessions=settings.live_session_max_sessions,
    )
    app.state.live_session_service = LiveEarningsSessionService(
        repository=app.state.live_session_repository,
        dispatcher=app.state.dispatch_analysis,
        evidence_service=app.state.evidence_service,
        company_service=app.state.company_intelligence_service,
        redis_publisher=app.state.redis_signal_publisher,
        settings=settings,
    )
    app.state.persist_envelope = lambda envelope: _persist_or_raise(app.state.event_store_repository, envelope)

    app.state.evidence_bootstrap_status = "disabled"
    app.state.evidence_bootstrap_error = None
    if settings.evidence_auto_bootstrap:
        try:
            evidence_bootstrapped = app.state.evidence_repository.bootstrap_schema()
            app.state.company_intelligence_repository.bootstrap_schema()
            app.state.evidence_bootstrap_status = "ready" if evidence_bootstrapped else "skipped"
        except Exception as exc:
            app.state.evidence_bootstrap_status = "error"
            app.state.evidence_bootstrap_error = f"{type(exc).__name__}: {exc}"

    async def _start_evidence_scheduler() -> None:
        if settings.phase1_warmup_on_startup:
            await asyncio.to_thread(app.state.analysis_service.phase1_scorer.warmup)
        await app.state.evidence_ingestion_scheduler.start()

    async def _stop_evidence_scheduler() -> None:
        await app.state.evidence_ingestion_scheduler.stop()

    app.router.add_event_handler("startup", _start_evidence_scheduler)
    app.router.add_event_handler("shutdown", _stop_evidence_scheduler)

    for router in ALL_ROUTERS:
        app.include_router(router)

    return app


app = create_app()


__all__ = [
    "HealthResponse",
    "_build_repository",
    "_dispatch_analysis",
    "_get_calibration_service",
    "_get_control_service",
    "_get_regression_service",
    "_persist_or_raise",
    "_schema_path_from_settings",
    "app",
    "create_app",
    "get_settings",
    "risk_score_from_sentiment",
    "run_analysis",
]
